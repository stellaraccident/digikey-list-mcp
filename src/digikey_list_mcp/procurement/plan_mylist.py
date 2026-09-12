from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import math
import secrets
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from digikey_list_mcp.config import Settings
from digikey_list_mcp.credentials import CredentialStore
from digikey_list_mcp.digikey.mylists import MyListsAPI
from digikey_list_mcp.digikey.product_information import ProductInformationAPI
from digikey_list_mcp.errors import PreviewError
from digikey_list_mcp.procurement.models import (
    ApplyResult,
    Part,
    PartVariation,
    PlannedLine,
    PreviewPlan,
    PreviewResult,
    RequestedLine,
    ValidationLine,
    ValidationResult,
)


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


class PreviewCodec:
    def __init__(self, store: CredentialStore) -> None:
        self.store = store

    def _secret(self) -> bytes:
        encoded = self.store.get("preview_signing_key")
        if not encoded:
            encoded = _b64encode(secrets.token_bytes(32))
            self.store.set("preview_signing_key", encoded)
        return _b64decode(encoded)

    def encode(self, plan: PreviewPlan) -> str:
        payload = plan.model_dump_json().encode("utf-8")
        signature = hmac.new(self._secret(), payload, hashlib.sha256).digest()
        return f"{_b64encode(payload)}.{_b64encode(signature)}"

    def decode(self, token: str) -> PreviewPlan:
        try:
            payload_encoded, signature_encoded = token.split(".", 1)
            payload = _b64decode(payload_encoded)
            signature = _b64decode(signature_encoded)
        except (ValueError, UnicodeError) as exc:
            raise PreviewError("The preview token is malformed.") from exc
        if _b64encode(payload) != payload_encoded or _b64encode(signature) != signature_encoded:
            raise PreviewError("The preview token is malformed.")
        expected = hmac.new(self._secret(), payload, hashlib.sha256).digest()
        if not hmac.compare_digest(signature, expected):
            raise PreviewError("The preview token was not issued by this installation.")
        try:
            plan = PreviewPlan.model_validate_json(payload)
        except ValueError as exc:
            raise PreviewError("The preview token contains an invalid plan.") from exc
        if plan.expires_at <= datetime.now(UTC):
            raise PreviewError("The preview expired; refresh pricing and create a new preview.")
        return plan

    @staticmethod
    def digest(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()


class OperationJournal:
    """Minimal local idempotency journal; never stores DigiKey catalog payloads."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (Settings.data_dir() / "applied-previews.json")

    def get(self, digest: str) -> ApplyResult | None:
        if not self.path.exists():
            return None
        data = json.loads(self.path.read_text(encoding="utf-8"))
        item = data.get(digest)
        return ApplyResult.model_validate(item) if item else None

    def put(self, digest: str, result: ApplyResult) -> None:
        data: dict[str, object] = {}
        if self.path.exists():
            data = json.loads(self.path.read_text(encoding="utf-8"))
        data[digest] = result.model_dump(mode="json")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(data), encoding="utf-8")
        tmp_path.chmod(0o600)
        tmp_path.replace(self.path)
        self.path.chmod(0o600)


class MyListPlanner:
    def __init__(
        self,
        products: ProductInformationAPI,
        mylists: MyListsAPI,
        settings: Settings,
        store: CredentialStore,
        *,
        journal: OperationJournal | None = None,
    ) -> None:
        self.products = products
        self.mylists = mylists
        self.settings = settings
        self.codec = PreviewCodec(store)
        self.journal = journal or OperationJournal()

    async def preview(
        self,
        lines: list[RequestedLine],
        *,
        list_id: str | None = None,
        list_name: str | None = None,
        assembly_count: int = 1,
    ) -> PreviewResult:
        if not lines:
            raise PreviewError("At least one line is required.")
        if not list_id and not list_name:
            raise PreviewError("Provide an existing list_id or a new list_name.")
        if assembly_count < 1:
            raise PreviewError("assembly_count must be at least 1.")

        parts = await asyncio.gather(*(self.products.get_part(line.part_number) for line in lines))
        planned = [
            self._plan_line(request, part, assembly_count=assembly_count)
            for request, part in zip(lines, parts, strict=True)
        ]
        totals = [line.extended_price for line in planned]
        estimated_total = sum((value for value in totals if value is not None), Decimal("0"))
        if all(value is None for value in totals):
            estimated_total = None
        warnings = [
            f"{line.digikey_product_number}: {warning}"
            for line in planned
            for warning in line.warnings
        ]
        now = datetime.now(UTC)
        plan = PreviewPlan(
            created_at=now,
            expires_at=now + timedelta(seconds=self.settings.preview_ttl_seconds),
            list_id=list_id,
            list_name=list_name,
            assembly_count=assembly_count,
            lines=planned,
            estimated_total=estimated_total,
            warnings=warnings,
        )
        return PreviewResult(plan=plan, preview_token=self.codec.encode(plan))

    async def apply(self, preview_token: str) -> ApplyResult:
        digest = self.codec.digest(preview_token)
        previous = self.journal.get(digest)
        if previous:
            return previous.model_copy(update={"already_applied": True})

        plan = self.codec.decode(preview_token)
        list_id = plan.list_id
        list_name = plan.list_name
        if not list_id:
            assert list_name is not None
            existing_named = await self.mylists.find_by_name(list_name)
            list_id = (
                existing_named.list_id
                if existing_named
                else await self.mylists.create_list(list_name)
            )

        existing = await self.mylists.get_list(list_id)
        existing_keys = {
            (
                (line.digikey_product_number or line.requested_part_number or "").casefold(),
                (line.customer_reference or "").casefold(),
                (line.reference_designator or "").casefold(),
                line.quantity,
                (line.package_type or "").casefold(),
            )
            for line in existing.lines
        }
        missing: list[PlannedLine] = []
        skipped: list[str] = []
        for line in plan.lines:
            key = (
                line.digikey_product_number.casefold(),
                (line.customer_reference or "").casefold(),
                (line.reference_designator or "").casefold(),
                line.final_quantity,
                (line.package_type or "").casefold(),
            )
            if key in existing_keys:
                skipped.append(line.digikey_product_number)
            else:
                missing.append(line)
        if missing:
            await self.mylists.add_lines(list_id, missing)

        result = ApplyResult(
            list_id=list_id,
            list_name=list_name or existing.name,
            added_product_numbers=[line.digikey_product_number for line in missing],
            skipped_existing_product_numbers=skipped,
        )
        self.journal.put(digest, result)
        return result

    async def validate(self, list_id: str) -> ValidationResult:
        mylist = await self.mylists.get_list(list_id)
        validations: list[ValidationLine] = []
        for line in mylist.lines:
            number = line.digikey_product_number or line.requested_part_number
            if not number:
                validations.append(
                    ValidationLine(line=line, warnings=["Line has no resolvable part number."])
                )
                continue
            try:
                part = await self.products.get_part(number)
            except Exception as exc:  # converted to a per-line warning for a complete report
                validations.append(
                    ValidationLine(line=line, warnings=[f"Could not refresh: {exc}"])
                )
                continue
            warnings = self._validation_warnings(line.quantity or 0, number, part)
            validations.append(ValidationLine(line=line, current_part=part, warnings=warnings))
        summary = [
            f"{item.line.digikey_product_number or item.line.requested_part_number}: {warning}"
            for item in validations
            for warning in item.warnings
        ]
        return ValidationResult(list_id=list_id, lines=validations, warnings=summary)

    @staticmethod
    def _plan_line(request: RequestedLine, part: Part, *, assembly_count: int) -> PlannedLine:
        requested_quantity = (
            request.quantity * assembly_count if request.per_assembly else request.quantity
        )
        adjusted = math.ceil(
            Decimal(requested_quantity) * (Decimal("1") + request.attrition_percent / 100)
        )
        variation = MyListPlanner._choose_variation(part, request, adjusted)
        final_quantity = max(adjusted, variation.minimum_order_quantity)
        unit_price = variation.unit_price_for(final_quantity)
        warnings = MyListPlanner._part_warnings(part, variation, final_quantity)
        if final_quantity != adjusted:
            warnings.append(
                f"Quantity raised from {adjusted} to MOQ {variation.minimum_order_quantity}."
            )
        if unit_price is None:
            warnings.append("No current unit price was returned.")
        elif request.target_price is not None and unit_price > request.target_price:
            warnings.append(f"Unit price {unit_price} exceeds target {request.target_price}.")
        return PlannedLine(
            requested_part_number=request.part_number,
            digikey_product_number=variation.digikey_product_number,
            manufacturer_product_number=part.manufacturer_product_number,
            manufacturer=part.manufacturer,
            description=part.description,
            requested_quantity=requested_quantity,
            attrition_adjusted_quantity=adjusted,
            final_quantity=final_quantity,
            package_type=variation.package_type,
            minimum_order_quantity=variation.minimum_order_quantity,
            quantity_available=variation.quantity_available,
            unit_price=unit_price,
            extended_price=unit_price * final_quantity if unit_price is not None else None,
            customer_reference=request.customer_reference,
            reference_designator=request.reference_designator,
            notes=request.notes,
            target_price=request.target_price,
            attrition_percent=request.attrition_percent,
            warnings=warnings,
            product_url=part.product_url,
            datasheet_url=part.datasheet_url,
        )

    @staticmethod
    def _choose_variation(part: Part, request: RequestedLine, quantity: int) -> PartVariation:
        if not part.variations:
            raise PreviewError(
                f"DigiKey did not return an orderable variation for {request.part_number}."
            )
        exact = [
            item
            for item in part.variations
            if item.digikey_product_number.casefold() == request.part_number.casefold()
        ]
        choices = exact or list(part.variations)
        if request.package_type:
            package_matches = [
                item
                for item in choices
                if request.package_type.casefold() in (item.package_type or "").casefold()
            ]
            if not package_matches:
                raise PreviewError(
                    f"No {request.package_type!r} package was returned for {request.part_number}."
                )
            choices = package_matches
        non_marketplace = [item for item in choices if not item.marketplace]
        choices = non_marketplace or choices

        def rank(item: PartVariation) -> tuple[int, int, Decimal, str]:
            enough_stock = item.quantity_available >= max(quantity, item.minimum_order_quantity)
            cut_tape = "cut tape" in (item.package_type or "").casefold()
            unit = item.unit_price_for(max(quantity, item.minimum_order_quantity))
            return (
                0 if enough_stock else 1,
                0 if cut_tape else 1,
                unit if unit is not None else Decimal("Infinity"),
                item.digikey_product_number,
            )

        return min(choices, key=rank)

    @staticmethod
    def _part_warnings(part: Part, variation: PartVariation, quantity: int) -> list[str]:
        warnings: list[str] = []
        if part.discontinued:
            warnings.append("Product is discontinued.")
        if part.end_of_life:
            warnings.append("Product is end-of-life.")
        if variation.marketplace:
            warnings.append("Selected variation is a DigiKey Marketplace item.")
        if variation.quantity_available < quantity:
            warnings.append(
                f"Only {variation.quantity_available} available for requested "
                f"order quantity {quantity}."
            )
        if not part.datasheet_url:
            warnings.append("No datasheet URL was returned.")
        return warnings

    @staticmethod
    def _validation_warnings(quantity: int, number: str, part: Part) -> list[str]:
        try:
            variation = MyListPlanner._choose_variation(
                part, RequestedLine(part_number=number, quantity=max(1, quantity)), max(1, quantity)
            )
        except PreviewError as exc:
            return [str(exc)]
        return MyListPlanner._part_warnings(part, variation, quantity)

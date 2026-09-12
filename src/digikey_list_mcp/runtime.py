from __future__ import annotations

from dataclasses import dataclass

from digikey_list_mcp.config import Settings
from digikey_list_mcp.credentials import CredentialStore, default_credential_store
from digikey_list_mcp.digikey import DigiKeyClient, MyListsAPI, ProductInformationAPI
from digikey_list_mcp.digikey.auth import DigiKeyOAuth
from digikey_list_mcp.procurement.plan_mylist import MyListPlanner


@dataclass
class Services:
    client: DigiKeyClient
    products: ProductInformationAPI
    mylists: MyListsAPI
    planner: MyListPlanner

    async def __aenter__(self) -> Services:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.client.aclose()


class Runtime:
    def __init__(
        self,
        settings: Settings | None = None,
        store: CredentialStore | None = None,
    ) -> None:
        self.settings = settings or Settings.load()
        self.store = store or default_credential_store()

    def services(self) -> Services:
        oauth = DigiKeyOAuth(self.settings, self.store)
        client = DigiKeyClient(self.settings, oauth)
        products = ProductInformationAPI(client)
        mylists = MyListsAPI(client)
        planner = MyListPlanner(products, mylists, self.settings, self.store)
        return Services(client=client, products=products, mylists=mylists, planner=planner)

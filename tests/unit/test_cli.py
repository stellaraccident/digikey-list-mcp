from digikey_list_mcp.cli import build_parser


def test_cli_defaults_to_stdio() -> None:
    args = build_parser().parse_args(["serve"])
    assert args.transport == "stdio"

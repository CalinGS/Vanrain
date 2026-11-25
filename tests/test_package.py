import vanrain
from vanrain.cli import main


def test_version():
    assert vanrain.__version__ == "0.0.1"


def test_stub_modules_import():
    import vanrain.graph  # noqa: F401
    import vanrain.mcp_server  # noqa: F401
    import vanrain.parsers.base  # noqa: F401
    import vanrain.parsers.python_ast  # noqa: F401
    import vanrain.render  # noqa: F401
    import vanrain.resolver  # noqa: F401
    import vanrain.seeds  # noqa: F401
    import vanrain.selector.base  # noqa: F401
    import vanrain.selector.bfs  # noqa: F401
    import vanrain.tokens  # noqa: F401


def test_cli_version(capsys):
    assert main(["--version"]) == 0
    assert "0.0.1" in capsys.readouterr().out

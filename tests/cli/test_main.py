from click.testing import CliRunner

from tcboard.cli.main import tcboard


def test_cli(runner: CliRunner) -> None:
    result = runner.invoke(tcboard)
    assert result.exit_code == 2

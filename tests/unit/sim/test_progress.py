"""The operator's view of a long harness command."""

import io

from tutor_sim.application.progress import CommandProgress


class Terminal(io.StringIO):
    """A stream that says it is a terminal, so the bar draws."""

    def isatty(self) -> bool:
        return True


class TestCommandProgress:
    def test_a_terminal_sees_the_bar_fill_then_the_summary(self) -> None:
        stream = Terminal()
        progress = CommandProgress(stream, width=10)
        progress.start(4)
        progress.step("c-000000 I1")
        progress.step("c-000001 I1")
        progress.step("c-000002 I2")
        progress.step("c-000003 I2")
        progress.finish("realised 4 cases")
        text = stream.getvalue()
        assert "[----------]   0% 0/4" in text
        assert "[#####-----]  50% 2/4 c-000001 I1" in text
        assert "[##########] 100% 4/4 c-000003 I2" in text
        assert text.endswith("\nrealised 4 cases\n")

    def test_a_redirected_stream_gets_only_the_summary(self) -> None:
        stream = io.StringIO()
        progress = CommandProgress(stream)
        progress.start(2)
        progress.step("a")
        progress.step("b")
        progress.finish("done")
        assert stream.getvalue() == "done\n"

    def test_a_command_without_items_prints_only_its_summary(self) -> None:
        stream = Terminal()
        progress = CommandProgress(stream)
        progress.finish("froze 0 cases")
        assert stream.getvalue() == "froze 0 cases\n"

    def test_a_resumed_command_starts_the_bar_at_the_items_already_done(
        self,
    ) -> None:
        stream = Terminal()
        progress = CommandProgress(stream, width=10)
        progress.start(4, done=2)
        progress.step("c-000002 I2")
        text = stream.getvalue()
        assert "[#####-----]  50% 2/4" in text
        assert "[#######---]  75% 3/4 c-000002 I2" in text

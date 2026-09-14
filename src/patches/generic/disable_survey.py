"""Option to disable the puzzle rating survey for playtesters"""
from models import PatchContext, ProgressCallback
from patches.base import atomic_write
from patches.definitions import PatchDefinition


SURVEY_CONFIG = b"cl_disable_survey_panel 1\r\n"
AUTOEXEC_COMMAND = b"exec patcher_disable_survey.cfg"


class DisableSurveyPatch:
    id = "disable_survey"
    display_name = "Disable Surveys"
    description = "Stop the difficulty and enjoyment survey for playtesters from appearing after maps."

    def _path(self, context: PatchContext):
        root = context.root / "game" if (context.root / "game" / "portal2").is_dir() else context.root
        return root / "portal2" / "cfg" / "patcher_disable_survey.cfg"

    def check(self, context: PatchContext) -> bool:
        path = self._path(context)
        autoexec = path.with_name("autoexec.cfg")
        return (
            not path.is_file() or path.read_bytes() != SURVEY_CONFIG
            or not autoexec.is_file()
            or AUTOEXEC_COMMAND not in [line.strip() for line in autoexec.read_bytes().splitlines()]
        )

    def apply(self, context: PatchContext, progress: ProgressCallback) -> None:
        path = self._path(context)
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(path, SURVEY_CONFIG)
        # autoexec runs after config.cfg, which can restore the archived cvar to 0.
        autoexec = path.with_name("autoexec.cfg")
        existing = autoexec.read_bytes() if autoexec.is_file() else b""
        if AUTOEXEC_COMMAND not in [line.strip() for line in existing.splitlines()]:
            separator = b"" if not existing or existing.endswith((b"\n", b"\r")) else b"\r\n"
            atomic_write(autoexec, existing + separator + AUTOEXEC_COMMAND + b"\r\n")

    def verify(self, context: PatchContext) -> None:
        if self.check(context):
            raise RuntimeError("Puzzle survey config failed verification")


DEFINITION = PatchDefinition(
    DisableSurveyPatch(),
    dependencies=frozenset({"launchers"}),
)

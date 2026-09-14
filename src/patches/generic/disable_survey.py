"""Option to disable the puzzle rating survey for playtesters"""
from models import PatchContext, ProgressCallback
from patches.base import atomic_write
from patches.definitions import PatchDefinition


SURVEY_CONFIG = b"cl_disable_survey_panel 1\r\n"


class DisableSurveyPatch:
    id = "disable_survey"
    display_name = "Disable Surveys"
    description = "Stop the difficulty and enjoyment survey for playtesters from appearing after maps."

    def _path(self, context: PatchContext):
        root = context.root / "game" if (context.root / "game" / "portal2").is_dir() else context.root
        return root / "portal2" / "cfg" / "patcher_disable_survey.cfg"

    def check(self, context: PatchContext) -> bool:
        path = self._path(context)
        return not path.is_file() or path.read_bytes() != SURVEY_CONFIG

    def apply(self, context: PatchContext, progress: ProgressCallback) -> None:
        path = self._path(context)
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(path, SURVEY_CONFIG)

    def verify(self, context: PatchContext) -> None:
        if self.check(context):
            raise RuntimeError("Puzzle survey config failed verification")


DEFINITION = PatchDefinition(
    DisableSurveyPatch(),
    dependencies=frozenset({"launchers"}),
)

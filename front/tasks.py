from background_task import background
from background_task.tasks import TaskSchedule

from core.utils.log_utils import info


@background(queue='main', schedule=TaskSchedule(priority=2))
def worker_run_copilot_turn(discussion_uuid: str, user_text: str):
    from front.services.copilot.runner import run_agent_turn
    try:
        run_agent_turn(discussion_uuid, user_text)
    except Exception as e:  # noqa: BLE001 - status is already set to ERROR by the runner
        info(f'copilot turn failed for {discussion_uuid}: {e}')


@background(queue='main', schedule=TaskSchedule(priority=2))
def worker_resume_copilot_turn(discussion_uuid: str, tool_call_id: str, approved: bool):
    from front.services.copilot.runner import resume_after_approval
    try:
        resume_after_approval(discussion_uuid, tool_call_id, approved)
    except Exception as e:  # noqa: BLE001
        info(f'copilot resume failed for {discussion_uuid}: {e}')

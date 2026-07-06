from background_task import background
from background_task.tasks import TaskSchedule


# The runner records the failure on the discussion (status=ERROR + error_message) for the UI and
# then re-raises, so we deliberately do NOT catch here: let it fail loudly to the worker logs /
# background-task retry, like crawling/tasks.py.
@background(queue='main', schedule=TaskSchedule(priority=2))
def worker_run_copilot_turn(discussion_uuid: str, user_text: str):
    from front.services.copilot.runner import run_agent_turn
    run_agent_turn(discussion_uuid, user_text)


@background(queue='main', schedule=TaskSchedule(priority=2))
def worker_resume_copilot_turn(discussion_uuid: str):
    from front.services.copilot.runner import resume_after_approval
    resume_after_approval(discussion_uuid)

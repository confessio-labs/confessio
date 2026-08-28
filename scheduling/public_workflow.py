from scheduling.workflows.parsing.compare_parsing_explanations import SchedulesListDiff, \
    build_schedules_list_diff, explain_schedules
from scheduling.workflows.parsing.schedules import SchedulesList
from scheduling.workflows.pruning.extract_and_join import extract_v2_refined_content


###################
# EXTRACT CONTENT #
###################

def scheduling_extract_v2_refined_content(refined_content: str) -> list[str] | None:
    return extract_v2_refined_content(refined_content)


#######################
# EXPLAINED SCHEDULES #
#######################

def scheduling_explain_schedules(schedules_list: SchedulesList | None,
                                 church_desc_by_id: dict[int, str]) -> list[str]:
    return explain_schedules(schedules_list, church_desc_by_id)


def scheduling_build_schedules_list_diff(before: SchedulesList | None,
                                         after: SchedulesList | None,
                                         church_desc_by_id: dict[int, str]) -> SchedulesListDiff:
    return build_schedules_list_diff(before, after, church_desc_by_id)

import asyncio
from typing import Optional

from core.utils.llm_utils import LLMProvider
from scheduling.workflows.parsing.llm_client import LLMClientInterface
from scheduling.workflows.parsing.openai_provider import get_openai_llm_client
from scheduling.workflows.parsing.rrule_utils import are_schedules_list_date_rule_valid, \
    is_schedules_list_explainable, filter_valid_schedules
from scheduling.workflows.parsing.schedules import SchedulesList, ScheduleItem


def get_prompt_template():
    return """Please help me extract the schedule of confession from the following French HTML
extract. A confession can be called "confession", "sacrement de réconciliation"
or "soirée de réconciliation, but not "heure de la miséricorde".

The output should be a dictionary with this format:
{{
    "schedules": list[ScheduleItem],  # list of schedule objects, see below
    "possible_by_appointment": bool, # whether the confession is possible by appointment,
        appointment is "rendez-vous" in French
    "is_related_to_mass": bool,  # whether the confession schedule is related to a mass
        schedule
    "is_related_to_adoration": bool,  # whether the confession schedule is related to a
        adoration schedule
    "is_related_to_permanence": bool,  # whether the confession schedule is related to a
        permanence schedule, can be called "permanence" or "accueil" in French.
    "will_be_seasonal_events": bool  # whether the text mentions future confession sessions
        during liturgical seasons, such as Lent or Advent.
}}

Then, "schedules" is a list of dictionaries, each containing the schedule for a church.
Sometimes several schedule dictionaries can be extracted for the same church.

Here is the schedule dictionary format:
{{
    "church_id": int | null,  # the id of the respective church, can be null if the
        church information is not explicit in the text. Can be -1 if the church is explicit and is
        not in the provided list. Sometimes, you can guess the church_id when it says
        "à la chapelle" and there is only one church called "chapelle" in the list.
        But if there is no mention, the church_id must be null.
    "date_rule": OneOffRule | RegularRule,  # the recurrence rule for the confession (see below)
    "is_cancellation": bool,  # whether this is a cancellation of a confession, e.g "pas de
        confession en août"
    "start_time_iso8601": str | null,  # the start time of the confession in "HH:MM:SS" format,
null if not explicit.
    "end_time_iso8601": str | null  # the end time of the confession in "HH:MM:SS" format,
null if not explicit.
}}

The field "date_rule" is a dictionary describing the date or the dates of confession event. It can
be a one-off date rule or a regular date rule.

Here is the one-off date rule format:
{{
    "year": int | null,  # the year as written in the text, let null if not explicit
    "month": int | null,  # month, let null if not explicit
    "day": int | null,  # day of month, let null if not explicit
    "weekday": Weekday | null,  # the week day, let null if not explicit
    "liturgical_day": LiturgicalDayEnum | null,  # the liturgical day, let null if not explicit
}}

For example, for "Vendredi 30 août", the one-off date rule would be:
{{
    "year": null,
    "month": 8,
    "day": 30,
    "weekday": "friday",
    "liturgical_day": null
}}, and for "30 août", the one-off date rule would be:
{{
    "year": null,
    "month": 8,
    "day": 30,
    "weekday": null,
    "liturgical_day": null
}}, for no date at all:
{{
    "year": null,
    "month": null,
    "day": null,
    "weekday": null,
    "liturgical_day": null
}}

The accepted LiturgicalDayEnum values are 'ash_wednesday', from 'palms_sunday' to 'easter_monday',
'ascension' and 'pentecost'.

Here is the regular date rule format:
{{
    "rule": DailyRule | WeeklyRule | MonthlyRule,  # the recurrence rule for the confession.
    "only_in_periods": list[PeriodEnum | CustomPeriod],  # the year periods when the rrule applied.
        For example, if the confession is only during the school holidays, the list would be
        ['school_holidays']. If the expression says "durant l'été", the list would be
        ['summer'].
    "not_in_periods": list[PeriodEnum | CustomPeriod]  # the year periods excluded. For example,
        if the confession is only during the school terms, the list would be ['school_holidays'].
        If the expression says "sauf pendant le carême", the list would be ['lent'].
    "not_on_dates": list[OneOffRule]  # the one-off dates excluded from the rrule.
}}

CustomPeriod is a dictionary with the following fields:
{{
    "start": OneOffRule,  # the start date of the period
    "end": OneOffRule,  # the end date of the period
}}
For example, if the expression says "sauf en août", the "not_in_periods" would be:
{{"start":{{"month":8,"day":1}},"end":{{"month":8,"day":30}}}}

DailyRule is an empty dictionary, WeeklyRule is a dictionary with the following format:
{{
    "by_weekdays": list[Weekday]  # the weekdays when the confession is held, e.g. ['monday',
        'wednesday', 'friday']
}}

MonthlyRule is a dictionary with the following format:
{{
    "by_nweekdays": list[NWeekday]  # the weekdays in a month when the confession is held,
        e.g. [{{'weekday': 'monday', 'position': 1}}, {{'weekday': 'friday', 'position': -1}}]
}}

NWeekday is a dictionary with the following format:
{{
    "weekday": Weekday,  # the weekday, e.g. 'monday'
    "position": Position  # the position of the weekday in a month, e.g. 1, 2, 3, 4, 5 or -1
}}

For example, for "le premier dimanche du mois", the "rule" would be:
{{"by_nweekdays":[{{"weekday":"sunday","position":1}}]}}
Warning: "un dimanche par mois", unlike "le premier dimanche du mois", is too vague and therefore
can not be translated into a schedule.

The accepted PeriodEnum values are:
- 'school_holidays'. If you need 'school_terms', just add 'school_holidays' to the opposite list.
- 'advent' or 'lent' for the liturgical seasons
- 'solemnities' for "jours de fêtes" or "jours de solennité"
- 'summer' or 'winter'

Some details:
- if a recurring event description is vague (e.g. "une fois par mois") and is followed by a list of
dates, prefer to return a list of one-off date rules instead of a regular date rule.
- If there is no explicit date in the text (e.g. "avant Noël", "avant Pâques", "une fois par mois",
"la semaine précédant les grandes fêtes religieuses" or no date at all), you can skip this schedule
or return a one off rule with all fields null.
- If there is no explicit time in the text (e.g. "dans la matinée", "dans l'après-midi",
"dans la soirée", "après la messe" or no time at all), you can skip this schedule or
set start_time_iso8601 and end_time_iso8601 to null.
- Usually, the lack of precision means some of the booleans for mass, adoration, permanence or
seasonal events should be set to True.
- A mass lasts 30 minutes, except on Sundays and feast days when it lasts 1 hour. Therefore, if the
confession starts "après la messe", two cases : either the schedule is explicit, e.g
"après la messe de Xh le vendredi" would give a start time of Xh30, or the schedule is not explicit,
e.g. "après la messe" would not give a schedule item dictionary.
- If the church is not explicit in the text, the church_id must be null.
- Sometimes you will be given a calendar, with month as title, day number as headers. In this case
you should return one-off date rules for each day number mentioned in the calendar.
- Sometimes, only the the start time of events are mentioned. In this case, you can set
end_time_iso8601 to null, or infer it from next event start time if relevant.
Example: "Xh confessions; Xh30 messe;"
would give start_time_iso8601 "0X:00:00" and end_time_iso8601 "0X:30:00".

Here is the HTML extract to parse:
{truncated_html}

The church ids and their names and location to consider:
{church_description}"""


def get_church_desc(church_desc_by_id: dict[int, str]):
    return "\n".join(f'{church_id}: {desc}'
                     for church_id, desc in church_desc_by_id.items())


def build_prompt_text(prompt_template: str,
                      truncated_html: str,
                      church_desc_by_id: dict[int, str]) -> str:
    church_description = get_church_desc(church_desc_by_id)

    return prompt_template.format(church_description=church_description,
                                  truncated_html=truncated_html)


def build_input_messages(prompt_template: str,
                         truncated_html: str,
                         church_desc_by_id: dict[int, str]) -> list[dict]:
    return [
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": build_prompt_text(prompt_template, truncated_html, church_desc_by_id)
                }
            ]
        }
    ]


def get_llm_client(llm_provider: LLMProvider = LLMProvider.OPENAI) -> LLMClientInterface:
    if llm_provider == LLMProvider.OPENAI:
        return get_openai_llm_client()

    raise ValueError(f"Unknown provider: {llm_provider}")


def replace_unknown_by_unique_church(schedules: list[ScheduleItem],
                                     church_desc_by_id: dict[int, str]) -> list[ScheduleItem]:
    if len(church_desc_by_id) != 1:
        return schedules

    unique_church_id = int(list(church_desc_by_id.keys())[0])

    new_schedules = []
    for schedule in schedules:
        if schedule.church_id is None:
            new_schedules.append(schedule.model_copy(update={'church_id': unique_church_id}))
        else:
            new_schedules.append(schedule)

    return new_schedules


async def parse_with_llm(truncated_html: str, church_desc_by_id: dict[int, str],
                         prompt_template: str, llm_client: Optional[LLMClientInterface]
                         ) -> tuple[SchedulesList | None, str | None]:
    schedules_list, llm_error_detail = await llm_client.get_completions(
        messages=build_input_messages(prompt_template, truncated_html, church_desc_by_id),
    )
    if schedules_list:
        schedules_list.schedules = filter_valid_schedules(schedules_list.schedules)

        if not are_schedules_list_date_rule_valid(schedules_list):
            return None, "Invalid date rule"

        is_explainable, not_explainable_detail = is_schedules_list_explainable(schedules_list)
        if not is_explainable:
            return None, f"Not explainable, reason: {not_explainable_detail}"

        schedules_list.schedules = replace_unknown_by_unique_church(schedules_list.schedules,
                                                                    church_desc_by_id)

    return schedules_list, llm_error_detail


if __name__ == '__main__':
    from dotenv import load_dotenv
    load_dotenv()
    # print(json.dumps(SchedulesList.model_json_schema()))

    truncated_html_ = ("Le sacrement de réconciliation est célébré à l'église Sainte-Marie tous "
                       "les jours de 17h à 18h, et le lundi 30 octobre de 10h à 10h30. Le père "
                       "Jean est disponible pour des confessions sur rendez-vous. Pas de "
                       "confession en août.")

    church_desc_by_id_ = {
        1: "Sainte-Marie, 123 rue de la Paix, 75000 Paris",
        2: "Saint-Joseph, 456 rue de la Liberté, 75000 Paris",
    }

    schedules_list_, llm_error_detail_ = asyncio.run(parse_with_llm(truncated_html_,
                                                                    church_desc_by_id_,
                                                                    get_prompt_template(),
                                                                    get_llm_client()))
    if schedules_list_:
        for schedule_ in schedules_list_.schedules:
            print(schedule_)
        print(schedules_list_.model_dump(exclude={'schedules'}))
    print(llm_error_detail_)

    # Expected output:
    # church_id=1
    # rrule='DTSTART:20240101T170000\nRRULE:FREQ=DAILY;BYHOUR=17;BYMINUTE=0'
    # duration_in_minutes=60
    # only_in_periods=[]
    # not_in_periods=[<PeriodEnum.AUGUST: 'august'>]
    # {'possible_by_appointment': True, 'is_related_to_mass': False,
    # 'is_related_to_adoration': False, 'is_related_to_permanence': False,
    # 'will_be_seasonal_events': False}
    # None

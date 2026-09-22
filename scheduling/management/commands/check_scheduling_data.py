from datetime import timedelta

from django.core.mail import mail_admins

from core.management.abstract_command import AbstractCommand
from core.utils.discord_utils import DiscordChanel, send_discord_alert
from core.utils.telegram_utils import TelegramTopic, send_telegram_alert
from scheduling.models import IndexEvent
from scheduling.workflows.parsing.holidays import check_holiday_by_zone
from scheduling.workflows.parsing.liturgical import check_easter_dates
from scheduling.utils.date_utils import get_current_day


class Command(AbstractCommand):
    help = "Check that holidays, easter dates, and index events are up to date"

    def handle(self, *args, **options):
        self.info('Starting checking future holidays and easter dates')
        holiday_ok = check_holiday_by_zone()
        easter_ok = check_easter_dates()
        if not holiday_ok or not easter_ok:
            error_message = (
                'Holiday failure: future holidays or easter dates are not '
                'implemented')
            self.error(error_message)
            message = f"""
            Holiday failure

            Future holidays or easter dates are not implemented
            Holiday: {holiday_ok}
            Easter: {easter_ok}
            """
            mail_admins(subject=error_message, message=message)
            send_discord_alert(message=message, channel=DiscordChanel.CRAWLING_ALERTS)
            send_telegram_alert(message=message, topic=TelegramTopic.CRAWLING_ALERTS)
            self.success('Email sent to admins')
        else:
            self.success('All future holidays and easter dates are implemented')

        self.info('Starting checking index events')
        yesterday = get_current_day() - timedelta(days=1)
        if IndexEvent.objects.filter(day__lt=yesterday).exists():
            error_message = 'Index events exist from yesterday or before'
            self.error(error_message)
            message = """
            Index events exist from yesterday or before

            You shall check the index_events job.
            """
            mail_admins(subject=error_message, message=message)
            send_discord_alert(message=message, channel=DiscordChanel.CRAWLING_ALERTS)
            send_telegram_alert(message=message, topic=TelegramTopic.CRAWLING_ALERTS)
            self.success('Email sent to admins')
        else:
            self.success('All index events are up to date')

from datetime import timedelta

from django.core.mail import mail_admins
from django.utils import timezone

from core.management.abstract_command import AbstractCommand
from core.utils.discord_utils import DiscordChanel, send_discord_alert
from core.utils.telegram_utils import TelegramTopic, send_telegram_alert
from crawling.models import Log as CrawlingLog
from registry.models import Website
from scheduling.models import Log as SchedulingLog
from scheduling.public_service import scheduling_get_indexed_scheduling


class Command(AbstractCommand):
    help = "Check that websites have been crawled and indexed recently"

    def handle(self, *args, **options):
        self.info('Starting checking crawling data')

        active_websites = Website.objects.filter(is_active=True).all()
        website_not_crawled = []
        website_not_crawled_recently = []
        website_not_indexed = []
        website_not_indexed_recently = []
        for website in active_websites:
            try:
                crawling_log = website.crawling_logs.filter(
                    type=CrawlingLog.Type.CRAWLING, status=CrawlingLog.Status.DONE)\
                    .order_by('-created_at').first()
            except CrawlingLog.DoesNotExist:
                crawling_log = None

            if crawling_log is None:
                website_not_crawled.append(website)
                continue

            # check that latest crawling is no older than 24 hours
            if crawling_log.created_at < timezone.now() - timedelta(days=1) \
                    and website.enabled_for_crawling:
                website_not_crawled_recently.append((website, crawling_log))
                continue

            scheduling = scheduling_get_indexed_scheduling(website)
            scheduling_log = SchedulingLog.objects.filter(
                website=website, status=SchedulingLog.Status.DONE,
                type=SchedulingLog.Type.PARSING
            ).order_by('-created_at').first()
            if scheduling is None or scheduling_log is None:
                website_not_indexed.append(website)
                continue

            # check that latest scheduling_log is no older than 24 hours
            if scheduling_log.created_at < timezone.now() - timedelta(days=1):
                website_not_indexed_recently.append(website)
                continue

        if website_not_crawled or website_not_crawled_recently or website_not_indexed \
                or website_not_indexed_recently:
            error_message = (
                f'Crawling failure: {len(website_not_crawled)} websites have never '
                f'been crawled and {len(website_not_crawled_recently)} have '
                f'not been crawled recently and {len(website_not_indexed)} have not '
                f'been indexed and {len(website_not_indexed_recently)} have not '
                f'been indexed recently')
            self.error(error_message)
            website_not_crawled_str = "\n".join(
                [f" - {website.name} {website.uuid}"
                 for website in website_not_crawled[:5]])
            website_not_crawled_recently_str = "\n".join(
                [f" - {cl.created_at} {ws.name} {ws.uuid}"
                 for ws, cl in website_not_crawled_recently[:5]])
            website_not_indexed_str = "\n".join(
                [f" - {website.name} {website.uuid}"
                 for website in website_not_indexed[:5]])
            website_not_indexed_recently_str = "\n".join(
                [f" - {website.name} {website.uuid}"
                 for website in website_not_indexed_recently[:5]])

            message = f"""
            Crawling failure

            Some websites not crawled (total {len(website_not_crawled)}):
            {website_not_crawled_str}

            Some websites not crawled recently (total {len(website_not_crawled_recently)}):
            {website_not_crawled_recently_str}

            Some websites not indexed (total {len(website_not_indexed)}):
            {website_not_indexed_str}

            Some websites not indexed recently (total {len(website_not_indexed_recently)}):
            {website_not_indexed_recently_str}
            """
            mail_admins(subject=error_message, message=message)
            send_discord_alert(message=message, channel=DiscordChanel.CRAWLING_ALERTS)
            send_telegram_alert(message=message, topic=TelegramTopic.CRAWLING_ALERTS)
            self.success('Email sent to admins')
        else:
            self.success('All websites have been crawled recently')

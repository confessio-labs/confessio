"""The SES event webhook: what became of the mails we sent.

SES publishes Delivery/Open/Bounce/Complaint to an SNS topic, which posts them here. django-ses
does the envelope work — SNS signature verification, the subscription handshake, and a 200 on
everything — so all this adds is the topic check it does not do, and the never-fail-the-webhook
policy the Mailgun route already follows.
"""
from django.conf import settings
from django_ses.views import SESEventWebhookView

from front.services.messaging.message_event_service import record_mail_event


class MailEventWebhookView(SESEventWebhookView):
    # csrf_exempt comes from the base class, which decorates dispatch: as_view() copies that onto
    # the view function, so there is nothing to re-declare here.

    def handle_delivery(self, notification, message):
        self._record(notification, message)

    def handle_open(self, notification, message):
        self._record(notification, message)

    def handle_bounce(self, notification, message):
        self._record(notification, message)

    def handle_complaint(self, notification, message):
        self._record(notification, message)

    def handle_subscription_confirmation(self, notification):
        """Only ever confirm our own topic.

        A valid signature proves the payload came from SNS, not that it came from us, and the
        base class confirms a subscription by simply fetching the url it was handed. Without this
        check anyone with an AWS account could point a topic of their own at this endpoint, have
        it confirmed, and then post whatever events they liked.
        """
        if not self._is_our_topic(notification):
            return
        super().handle_subscription_confirmation(notification)

    def _record(self, notification, message):
        if not self._is_our_topic(notification):
            return
        try:
            record_mail_event(message)
        except Exception as e:
            # Never fail the webhook on an ingestion problem: SNS would retry it for hours, and a
            # missing tick is not worth a retry storm.
            print(e)

    @staticmethod
    def _is_our_topic(notification) -> bool:
        expected = getattr(settings, 'AWS_SES_EVENT_TOPIC_ARN', '')
        if not expected:
            # Unset in dev, where the payloads are hand-written and nothing is signed anyway.
            return True
        topic_arn = notification.get('TopicArn')
        if topic_arn != expected:
            print(f"Ignoring SNS notification from unexpected topic: {topic_arn}")
            return False
        return True

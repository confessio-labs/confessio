Deployment in production instructions.

## OVH

Create a public cloud instance `discovery` `d2-2` in Gravelines, on public network,
using ubuntu 24.04.1, with a name like `confessio-1`.

Add the following firewall configuration:
![OVHcloud.png](./OVHcloud.png)

Buy a domain and link DNS to your instance IP.
![Domaines.png](./Domaines-SSL-IONOS.png)

## AWS S3

We use S3 to backup postgresql daily and weekly, as well as to store uploaded documents.

Create three S3 buckets and an IAM user ([tutorial](https://kinsta.com/knowledgebase/amazon-s3-backups/)).
The S3 buckets to create are:
- `confessio-dbbackup-daily`
- `confessio-dbbackup-weekly`
- `confessio-uploaded-documents`

For security reasons, we don't want the IAM user to be able to delete any elements in them.

Here is the policy:
```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "atbucket",
            "Effect": "Allow",
            "Action": [
                "s3:PutObject",
                "s3:GetObjectAcl",
                "s3:GetObject",
                "s3:ListBucket",
                "s3:GetBucketAcl",
                "s3:PutObjectAcl"
            ],
            "Resource": [
                "arn:aws:s3:::confessio-dbbackup-daily",
                "arn:aws:s3:::confessio-dbbackup-daily/*",
                "arn:aws:s3:::confessio-dbbackup-weekly",
                "arn:aws:s3:::confessio-dbbackup-weekly/*",
                "arn:aws:s3:::confessio-uploaded-documents",
                "arn:aws:s3:::confessio-uploaded-documents/*"
            ]
        },
        {
            "Sid": "overall",
            "Effect": "Allow",
            "Action": [
                "s3:ListAllMyBuckets"
            ],
            "Resource": "*"
        }
    ]
}
```

Also, to enable public download of uploaded documents, you need to set the bucket policy for `confessio-uploaded-documents` to allow public read access:
```json
{
	"Version": "2012-10-17",
	"Statement": [
		{
			"Sid": "PublicReadAllObjects",
			"Effect": "Allow",
			"Principal": "*",
			"Action": "s3:GetObject",
			"Resource": "arn:aws:s3:::confessio-uploaded-documents/*"
		}
	]
}
```

Also, you should add CloudWatch alarms to monitor the buckets size.
![img.png](s3_cloudwatch_alarms.png)
In CloudWatch, go to metrics, browse S3 metrics, and for both buckets create an alarm on size. Don't forget to confirm the email subscription in your inbox.


## AWS SES
We use AWS SES to send email.

Here is a policy to add to the IAM user to allow email sending:
```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "VisualEditor0",
            "Effect": "Allow",
            "Action": [
                "ses:SendEmail",
                "ses:GetSendQuota",
                "ses:SendRawEmail"
            ],
            "Resource": "*"
        }
    ]
}
```

You'll have to verify domain and some email address on SES console.

### SES event webhook (accusés de réception)

`/webhooks/mail_events` records what became of each outbound mail (delivered, opened, bounced,
complained), which is what draws the ticks in `/messaging`. SES only publishes events for mails
tagged with a configuration set, so nothing happens until this is wired, in this order — the
endpoint must be live before the subscription is created, because confirmation is automatic:

1. Deploy the code, so `https://<host>/webhooks/mail_events` answers.
2. SNS → create a Standard topic, e.g. `confessio-ses-events`, in the same region as
   `AWS_SES_REGION_NAME` (eu-west-3).
3. SES → Configuration sets → create one, e.g. `confessio-events`.
4. On that set, add an event destination pointing at the topic, with event types
   **Delivery, Open, Bounce, Complaint**.

   **Do not subscribe to `Click`.** SES rewrites every link to `awstrack.me` as soon as a Click
   destination exists, and `find_conversation` reads the `/messaging/<uuid>` url out of the
   quoted HTML of inbound replies to thread them. Open only adds a tracking pixel and leaves
   links alone.
5. SNS → create an HTTPS subscription on the topic pointing at the endpoint, with **raw message
   delivery OFF** (django-ses needs the SNS envelope). It should flip to Confirmed on its own; if
   it stays Pending, the app rejected it — check `AWS_SES_EVENT_TOPIC_ARN`.
6. Set `AWS_SES_CONFIGURATION_SET` and `AWS_SES_EVENT_TOPIC_ARN` in the environment and redeploy.

No IAM change: `ses:SendRawEmail` already covers sending with a configuration set, and it is SES
itself, not our IAM user, that publishes to the topic. The console writes the topic access policy
allowing `ses.amazonaws.com` to `sns:Publish` when the destination is created.

`AWS_SES_EVENT_TOPIC_ARN` is a security control, not a convenience: a valid SNS signature only
proves the payload came from AWS, not that it came from our topic. Without it, anyone could point
a topic of their own at the endpoint and post forged events.

### AWS CloudWatch

Create a loggroup in AWS CloudWatch called "/metrics/opentelemetry", 
and in it a log stream "confessio-stream".
Create an IAM user "otel-metrics-agent", with "CloudWatchAgentServerPolicy" permissions.
Export the access key and secret key.

You can check the permissions in server by doing :
```shell
sudo su - otel
aws logs put-log-events --log-group-name "/metrics/opentelemetry" --log-stream-name "confessio-stream" --log-events timestamp=$(date +%s%3N),message="Test log event" --region eu-west-3
```

## Run ansible playbook

### Install Ansible dependencies

Install latest grafana.grafana ansible collection:
```
ansible-galaxy collection install grafana.grafana --force
```

### Run playbook

```shell
# first installation of server
./prod.sh install
# after any change of code
./prod.sh deploy
# once and after any cron change
./prod.sh cron
```
This is mainly inspired by https://realpython.com/automating-django-deployments-with-fabric-and-ansible/

### Restore DB backup
```shell
# SSH to server then grant confessio postgresql superuser privilege
# This is required because backup will drop/create postgis extension
sudo -u postgres psql -c "ALTER ROLE confessio SUPERUSER;"
# Drop and recreate database
sudo -u postgres psql postgres -c "DROP DATABASE confessio;" && sudo -u postgres psql postgres -c "CREATE DATABASE confessio;" && sudo -u postgres psql postgres -c "ALTER DATABASE confessio OWNER TO confessio;"
# This will restore last backup
. /home/ubuntu/confessio/.env; /home/ubuntu/confessio/.venv/bin/python3.13 /home/ubuntu/confessio/manage.py dbrestore --uncompress --database default
# Revoke superuser access
sudo -u postgres psql -c "ALTER ROLE confessio NOSUPERUSER;"
```

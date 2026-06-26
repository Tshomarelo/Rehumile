"""
Management command: check_sla_breaches

Run periodically (e.g. every 15 min via cron/Celery beat) to:
  1. Flag incidents that have passed their SLA deadlines
  2. Create SLABreach records for newly breached incidents
  3. Create Notification records for affected users/agents
"""

from django.core.management.base import BaseCommand
from django.utils import timezone
from ims.models import Incident, SLABreach, Notification, NotificationTypeChoices


class Command(BaseCommand):
    help = 'Check for SLA breaches and create breach records + notifications'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Print what would be done without making changes',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        now = timezone.now()

        active_incidents = Incident.objects.filter(
            status__in=['open', 'in_progress'],
            is_sla_breached=False,
        ).select_related('company', 'submitted_by', 'assigned_to')

        newly_breached = 0
        warnings_sent = 0

        for incident in active_incidents:
            breach_type = None
            deadline = None

            # Check response deadline first
            if incident.response_deadline and incident.response_deadline < now:
                breach_type = 'response'
                deadline = incident.response_deadline
            elif incident.resolution_deadline and incident.resolution_deadline < now:
                breach_type = 'resolution'
                deadline = incident.resolution_deadline

            if breach_type:
                minutes_over = int((now - deadline).total_seconds() / 60)

                if dry_run:
                    self.stdout.write(
                        f'[DRY RUN] Would breach: {incident.ticket_id} '
                        f'({breach_type}, {minutes_over} min over)'
                    )
                    newly_breached += 1
                    continue

                # Mark incident as breached
                incident.is_sla_breached = True
                incident.is_escalated = True
                incident.save(update_fields=['is_sla_breached', 'is_escalated'])

                # Create SLABreach record
                if incident.company:
                    SLABreach.objects.get_or_create(
                        incident=incident,
                        breach_type=breach_type,
                        defaults={
                            'company': incident.company,
                            'breached_at': deadline,
                            'time_over': minutes_over,
                        },
                    )

                # Notify assigned agent
                if incident.assigned_to:
                    Notification.objects.create(
                        user=incident.assigned_to,
                        notification_type=NotificationTypeChoices.SLA_BREACH,
                        title=f'SLA Breached — {incident.ticket_id}',
                        message=(
                            f'Ticket "{incident.title}" has breached its '
                            f'{breach_type} SLA by {minutes_over} minutes.'
                        ),
                        incident=incident,
                    )

                # Notify submitter
                if incident.submitted_by and incident.submitted_by != incident.assigned_to:
                    Notification.objects.create(
                        user=incident.submitted_by,
                        notification_type=NotificationTypeChoices.SLA_BREACH,
                        title=f'SLA Breached — {incident.ticket_id}',
                        message=(
                            f'Your ticket "{incident.title}" has exceeded its '
                            f'{breach_type} SLA deadline.'
                        ),
                        incident=incident,
                    )

                newly_breached += 1
                self.stdout.write(
                    self.style.WARNING(
                        f'Breached: {incident.ticket_id} ({breach_type}, {minutes_over} min over)'
                    )
                )
            else:
                # Check for approaching deadlines (within 2 hours) — send warning
                warning_deadline = None
                if incident.response_deadline:
                    hours_left = (incident.response_deadline - now).total_seconds() / 3600
                    if 0 < hours_left <= 2:
                        warning_deadline = incident.response_deadline
                elif incident.resolution_deadline:
                    hours_left = (incident.resolution_deadline - now).total_seconds() / 3600
                    if 0 < hours_left <= 2:
                        warning_deadline = incident.resolution_deadline

                if warning_deadline and not dry_run and incident.assigned_to:
                    # Only create warning if one doesn't already exist in last hour
                    already_warned = Notification.objects.filter(
                        user=incident.assigned_to,
                        incident=incident,
                        notification_type=NotificationTypeChoices.SLA_WARNING,
                        created_at__gte=now - timezone.timedelta(hours=1),
                    ).exists()

                    if not already_warned:
                        hours_left = round((warning_deadline - now).total_seconds() / 3600, 1)
                        Notification.objects.create(
                            user=incident.assigned_to,
                            notification_type=NotificationTypeChoices.SLA_WARNING,
                            title=f'SLA Warning — {incident.ticket_id}',
                            message=(
                                f'Ticket "{incident.title}" SLA deadline is in '
                                f'{hours_left} hours. Please act now.'
                            ),
                            incident=incident,
                        )
                        warnings_sent += 1

        prefix = '[DRY RUN] ' if dry_run else ''
        self.stdout.write(
            self.style.SUCCESS(
                f'{prefix}Done. Breaches: {newly_breached}, Warnings sent: {warnings_sent}'
            )
        )

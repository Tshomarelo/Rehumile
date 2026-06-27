from django.shortcuts import render
from django.utils import timezone
from django.contrib.auth import get_user_model
from django.core.mail import EmailMultiAlternatives
from django.conf import settings as django_settings
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from rest_framework import viewsets, status, generics, serializers as drf_serializers
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.decorators import action
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth import authenticate
import uuid
import json


@csrf_exempt
@require_POST
def quote_request_view(request):
    """Handle quote requests from the main website — used in production (PythonAnywhere)."""
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'error': 'Invalid JSON.'}, status=400)

    name = data.get('name', '').strip()
    email = data.get('email', '').strip()
    phone = data.get('phone', '').strip()
    company = data.get('company', '').strip()
    service = data.get('service', '').strip() or 'General Enquiry'
    message = data.get('message', '').strip()

    if not name or not email or not message:
        return JsonResponse({'error': 'Name, email and message are required.'}, status=400)

    html_body = f"""
<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#f5f5f5;font-family:Arial,sans-serif">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f5f5f5;padding:32px 0">
    <tr><td align="center">
      <table width="600" cellpadding="0" cellspacing="0" style="background:#ffffff;border-radius:8px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.08)">
        <tr>
          <td style="background:#50181E;padding:28px 32px">
            <h1 style="margin:0;color:#B38F43;font-size:22px;font-weight:700;letter-spacing:1px">REHUMILE TMW</h1>
            <p style="margin:4px 0 0;color:#ffffff;font-size:13px;opacity:0.8">New Quote Request Received</p>
          </td>
        </tr>
        <tr>
          <td style="padding:32px">
            <table width="100%" cellpadding="0" cellspacing="0">
              <tr><td style="padding-bottom:16px;border-bottom:1px solid #eee">
                <p style="margin:0;font-size:13px;color:#888">Full Name</p>
                <p style="margin:4px 0 0;font-size:16px;color:#222;font-weight:600">{name}</p>
              </td></tr>
              <tr><td style="padding:16px 0;border-bottom:1px solid #eee">
                <p style="margin:0;font-size:13px;color:#888">Email</p>
                <p style="margin:4px 0 0;font-size:15px;color:#222"><a href="mailto:{email}" style="color:#50181E">{email}</a></p>
              </td></tr>
              {'<tr><td style="padding:16px 0;border-bottom:1px solid #eee"><p style="margin:0;font-size:13px;color:#888">Phone</p><p style="margin:4px 0 0;font-size:15px;color:#222">' + phone + '</p></td></tr>' if phone else ''}
              {'<tr><td style="padding:16px 0;border-bottom:1px solid #eee"><p style="margin:0;font-size:13px;color:#888">Company</p><p style="margin:4px 0 0;font-size:15px;color:#222">' + company + '</p></td></tr>' if company else ''}
              <tr><td style="padding:16px 0;border-bottom:1px solid #eee">
                <p style="margin:0;font-size:13px;color:#888">Service Required</p>
                <p style="margin:4px 0 0;font-size:15px;color:#50181E;font-weight:600">{service}</p>
              </td></tr>
              <tr><td style="padding:16px 0">
                <p style="margin:0;font-size:13px;color:#888">Message</p>
                <p style="margin:8px 0 0;font-size:15px;color:#333;line-height:1.6;background:#fafafa;padding:12px;border-left:3px solid #B38F43;border-radius:2px">{message.replace(chr(10), '<br>')}</p>
              </td></tr>
            </table>
          </td>
        </tr>
        <tr><td style="background:#f9f9f9;padding:16px 32px;border-top:1px solid #eee">
          <p style="margin:0;font-size:12px;color:#aaa;text-align:center">Submitted via the Rehumile TMW website contact form.</p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""

    confirm_html = f"""
<!DOCTYPE html><html>
<body style="margin:0;padding:0;background:#f5f5f5;font-family:Arial,sans-serif">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f5f5f5;padding:32px 0">
    <tr><td align="center">
      <table width="600" cellpadding="0" cellspacing="0" style="background:#fff;border-radius:8px;overflow:hidden">
        <tr><td style="background:#50181E;padding:28px 32px">
          <h1 style="margin:0;color:#B38F43;font-size:22px;font-weight:700">REHUMILE TMW</h1>
          <p style="margin:4px 0 0;color:#fff;font-size:13px;opacity:0.8">Quote Request Confirmation</p>
        </td></tr>
        <tr><td style="padding:32px">
          <p style="font-size:15px;color:#333">Hi <strong>{name}</strong>,</p>
          <p style="font-size:15px;color:#333;line-height:1.7">Thank you for reaching out to <strong>Rehumile TMW</strong>. We have received your quote request for <strong style="color:#50181E">{service}</strong> and will be in touch shortly.</p>
          <p style="font-size:15px;color:#333;line-height:1.7">For urgent matters call <strong>068 397 3484</strong> or email <a href="mailto:infor@rehumile.co.za" style="color:#50181E">infor@rehumile.co.za</a>.</p>
          <p style="font-size:14px;color:#888;margin-top:24px">Warm regards,<br><strong style="color:#50181E">The Rehumile TMW Team</strong></p>
        </td></tr>
        <tr><td style="background:#f9f9f9;padding:16px 32px;border-top:1px solid #eee">
          <p style="margin:0;font-size:12px;color:#aaa;text-align:center">© 2026 Rehumile TMW · Jozini, KwaZulu-Natal, South Africa</p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body></html>"""

    try:
        msg = EmailMultiAlternatives(
            subject=f'Quote Request: {service} — {name}',
            body=f'New quote request from {name} ({email}) for {service}.\n\n{message}',
            from_email=django_settings.DEFAULT_FROM_EMAIL,
            to=['infor@rehumile.co.za'],
            reply_to=[email],
        )
        msg.attach_alternative(html_body, 'text/html')
        msg.send()

        confirm = EmailMultiAlternatives(
            subject='We received your quote request — Rehumile TMW',
            body=f'Hi {name}, we received your quote request and will be in touch soon.',
            from_email=django_settings.DEFAULT_FROM_EMAIL,
            to=[email],
        )
        confirm.attach_alternative(confirm_html, 'text/html')
        confirm.send()

        return JsonResponse({'success': True})
    except Exception as exc:
        return JsonResponse({'error': str(exc)}, status=500)


def _send_ticket_notification(incident, user):
    """Send ticket confirmation email to submitter and admin@rehumile.co.za."""
    try:
        submitter_name = f"{user.first_name} {user.last_name}".strip() or user.email
        company_name = incident.company.name if incident.company else 'N/A'
        priority_label = incident.get_priority_display().upper()
        category_label = incident.get_category_display()
        logged_at = incident.created_at.strftime('%d %b %Y %H:%M') if incident.created_at else ''

        priority_colours = {
            'critical': ('#dc3545', '#fff'),
            'high':     ('#fd7e14', '#fff'),
            'medium':   ('#ffc107', '#212529'),
            'low':      ('#28a745', '#fff'),
        }
        bg, fg = priority_colours.get(incident.priority, ('#6c757d', '#fff'))

        subject = f"[Rehumile IMS] Ticket {incident.ticket_id} Logged: {incident.title}"

        text_body = (
            f"Dear {submitter_name},\n\n"
            f"Your support ticket has been successfully logged with Rehumile TMW.\n\n"
            f"─────────────────────────────────────\n"
            f"Ticket Reference : {incident.ticket_id}\n"
            f"Title            : {incident.title}\n"
            f"Priority         : {priority_label}\n"
            f"Category         : {category_label}\n"
            f"Company          : {company_name}\n"
            f"Status           : Open\n"
            f"Logged           : {logged_at}\n"
            f"─────────────────────────────────────\n\n"
            f"Our team will review your ticket and respond shortly.\n"
            f"Log in to the client portal to track updates or add comments.\n\n"
            f"Best regards,\n"
            f"Rehumile TMW Support Team\n"
            f"support@rehumile.co.za\n"
        )

        html_body = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#f4f4f4;font-family:Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f4f4f4;padding:30px 0;">
    <tr><td align="center">
      <table width="600" cellpadding="0" cellspacing="0" style="background:#fff;border-radius:8px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,.1);">
        <tr><td style="background:#50181E;padding:24px 32px;">
          <h1 style="margin:0;color:#B38F43;font-size:22px;font-weight:700;letter-spacing:1px;">Rehumile TMW</h1>
          <p style="margin:4px 0 0;color:rgba(255,255,255,.8);font-size:12px;text-transform:uppercase;letter-spacing:2px;">Consulting &bull; Development &bull; Training</p>
        </td></tr>
        <tr><td style="padding:32px;">
          <p style="color:#333;font-size:15px;margin-top:0;">Dear <strong>{submitter_name}</strong>,</p>
          <p style="color:#555;font-size:14px;">Your support ticket has been successfully logged. Our team will review it and be in touch shortly.</p>
          <table width="100%" cellpadding="0" cellspacing="0" style="background:#fafafa;border-radius:6px;border-left:4px solid #50181E;margin:20px 0;">
            <tr><td style="padding:20px;">
              <p style="margin:0 0 12px;color:#888;font-size:11px;text-transform:uppercase;letter-spacing:1px;">Ticket Details</p>
              <table width="100%" cellpadding="5" cellspacing="0" style="font-size:14px;">
                <tr>
                  <td style="color:#888;width:130px;vertical-align:top;">Reference</td>
                  <td><strong style="color:#50181E;font-family:monospace;font-size:16px;">{incident.ticket_id}</strong></td>
                </tr>
                <tr>
                  <td style="color:#888;vertical-align:top;">Title</td>
                  <td style="color:#333;"><strong>{incident.title}</strong></td>
                </tr>
                <tr>
                  <td style="color:#888;vertical-align:top;">Priority</td>
                  <td><span style="background:{bg};color:{fg};padding:2px 10px;border-radius:4px;font-size:12px;font-weight:700;">{priority_label}</span></td>
                </tr>
                <tr>
                  <td style="color:#888;vertical-align:top;">Category</td>
                  <td style="color:#333;">{category_label}</td>
                </tr>
                <tr>
                  <td style="color:#888;vertical-align:top;">Company</td>
                  <td style="color:#333;">{company_name}</td>
                </tr>
                <tr>
                  <td style="color:#888;vertical-align:top;">Status</td>
                  <td><span style="background:#28a745;color:#fff;padding:2px 10px;border-radius:4px;font-size:12px;font-weight:700;">OPEN</span></td>
                </tr>
                <tr>
                  <td style="color:#888;vertical-align:top;">Logged</td>
                  <td style="color:#555;">{logged_at}</td>
                </tr>
              </table>
            </td></tr>
          </table>
          <p style="color:#888;font-size:12px;margin-bottom:0;">Please do not reply to this email. Log in to the portal to add comments or track progress.</p>
        </td></tr>
        <tr><td style="background:#f8f8f8;padding:14px 32px;border-top:1px solid #eee;text-align:center;">
          <p style="margin:0;color:#bbb;font-size:11px;">Rehumile TMW IMS &bull; support@rehumile.co.za</p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body></html>"""

        recipients = list(dict.fromkeys(
            e for e in [user.email, 'admin@rehumile.co.za'] if e
        ))
        msg = EmailMultiAlternatives(
            subject=subject,
            body=text_body,
            from_email=django_settings.DEFAULT_FROM_EMAIL,
            to=recipients,
        )
        msg.attach_alternative(html_body, 'text/html')
        msg.send(fail_silently=False)
    except Exception as exc:
        import logging
        logging.getLogger('ims.email').error('Ticket notification failed for %s: %s', incident.ticket_id, exc)

from .models import (
    Company, UserProfile, Incident, IncidentComment,
    SLAConfig, StatusChoices, Invoice,
    Notification, AuditLog, SLABreach, IncidentAttachment,
    JobCard, JobCardStatusChoices,
    InventoryItem, StockTransaction,
    ShiftLog, CashTransaction, CashFlowStreamChoices,
    Voucher, PurchaseSlip,
)
from .serializers import (
    CompanySerializer, UserSerializer, UserCreateSerializer,
    IncidentSerializer, IncidentCreateSerializer,
    IncidentCommentSerializer, DashboardMetricsSerializer, InvoiceSerializer
)
from .permissions import IsHQAdmin, IsHQAdminOrAgent, IsHQAdminOrReadOnly, IsHQStaff

User = get_user_model()


# ============================================================================
# AUTH VIEWS
# ============================================================================

class LoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        email = request.data.get('email', '')
        password = request.data.get('password', '')

        if not email or not password:
            return Response(
                {'detail': 'Email and password are required.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        user = authenticate(request, username=email, password=password)
        if user is None:
            try:
                user_obj = User.objects.get(email=email)
                user = authenticate(request, username=user_obj.username, password=password)
            except User.DoesNotExist:
                pass

        if user is None or not user.is_active:
            return Response(
                {'detail': 'Invalid credentials.'},
                status=status.HTTP_401_UNAUTHORIZED
            )

        refresh = RefreshToken.for_user(user)
        return Response({
            'access': str(refresh.access_token),
            'refresh': str(refresh),
            'user': {
                'id': str(user.id),
                'email': user.email,
                'first_name': user.first_name,
                'last_name': user.last_name,
                'role': user.role,
                'company_id': str(user.company.id) if user.company else None,
                'company_name': user.company.name if user.company else None,
            }
        })


class RegisterView(APIView):
    """Public self-registration — creates a client account and returns JWT tokens."""
    permission_classes = [AllowAny]

    def post(self, request):
        first_name = request.data.get('first_name', '').strip()
        last_name = request.data.get('last_name', '').strip()
        email = request.data.get('email', '').strip().lower()
        password = request.data.get('password', '')
        company_name = request.data.get('company_name', '').strip()

        if not first_name or not email or not password:
            return Response({'detail': 'First name, email and password are required.'}, status=400)
        if len(password) < 8:
            return Response({'detail': 'Password must be at least 8 characters.'}, status=400)
        if User.objects.filter(email=email).exists():
            return Response({'detail': 'An account with this email already exists.'}, status=400)

        username = email.split('@')[0]
        base = username
        count = 1
        while User.objects.filter(username=username).exists():
            username = f"{base}{count}"
            count += 1

        user = User.objects.create_user(
            username=username,
            email=email,
            password=password,
            first_name=first_name,
            last_name=last_name,
            role='client',
        )

        if company_name:
            from .models import Company
            company, _ = Company.objects.get_or_create(name=company_name)
            user.company = company
            user.save()

        refresh = RefreshToken.for_user(user)
        return Response({
            'access': str(refresh.access_token),
            'refresh': str(refresh),
            'user': {
                'id': str(user.id),
                'email': user.email,
                'first_name': user.first_name,
                'last_name': user.last_name,
                'role': user.role,
                'company_id': str(user.company.id) if user.company else None,
                'company_name': user.company.name if user.company else None,
            }
        }, status=201)


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            refresh_token = request.data.get('refresh')
            if refresh_token:
                token = RefreshToken(refresh_token)
                token.blacklist()
        except Exception:
            pass
        return Response({'detail': 'Logged out successfully.'})


class MeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        return Response({
            'id': str(user.id),
            'email': user.email,
            'first_name': user.first_name,
            'last_name': user.last_name,
            'role': user.role,
            'status': user.status,
            'company': str(user.company.id) if user.company else None,
            'company_name': user.company.name if user.company else None,
        })

    def patch(self, request):
        user = request.user
        allowed_fields = {'first_name', 'last_name'}
        for field in allowed_fields:
            if field in request.data:
                setattr(user, field, request.data[field])
        user.save()
        return self.get(request)


class ChangePasswordView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        old_password = request.data.get('old_password', '')
        new_password = request.data.get('new_password', '')

        if not user.check_password(old_password):
            return Response(
                {'old_password': ['Current password is incorrect.']},
                status=status.HTTP_400_BAD_REQUEST
            )
        if len(new_password) < 8:
            return Response(
                {'new_password': ['Password must be at least 8 characters.']},
                status=status.HTTP_400_BAD_REQUEST
            )
        user.set_password(new_password)
        user.save()
        return Response({'detail': 'Password updated successfully.'})


# ============================================================================
# COMPANY VIEWS
# ============================================================================

class CompanyViewSet(viewsets.ModelViewSet):
    """
    Company management.
    - List/retrieve: any authenticated user (filtered by company for non-admins)
    - Create/update/delete: HQ Admin only
    """

    def get_permissions(self):
        if self.action in ('create', 'update', 'partial_update', 'destroy'):
            return [IsHQAdmin()]
        return [IsAuthenticated()]

    def get_serializer_class(self):
        return CompanySerializer

    def get_queryset(self):
        user = self.request.user
        if user.role in ('admin', 'agent', 'finance'):
            return Company.objects.filter(is_deleted=False).order_by('-created_at')
        if user.company:
            return Company.objects.filter(id=user.company.id, is_deleted=False)
        return Company.objects.none()

    def perform_destroy(self, instance):
        instance.is_deleted = True
        instance.save()


# ============================================================================
# USER VIEWS
# ============================================================================

class UserViewSet(viewsets.ModelViewSet):
    """
    User management.
    - List/retrieve: HQ Admin or Agent (filtered for others)
    - Create/update: HQ Admin only
    - Status patch: HQ Admin only
    """

    def get_permissions(self):
        if self.action in ('create', 'update', 'partial_update', 'destroy', 'update_status'):
            return [IsHQAdmin()]
        return [IsHQAdminOrAgent()]

    def get_serializer_class(self):
        if self.action == 'create':
            return UserCreateSerializer
        return UserSerializer

    def get_queryset(self):
        user = self.request.user
        if user.role in ('admin', 'agent'):
            return User.objects.all().order_by('-created_at')
        if user.company:
            return User.objects.filter(company=user.company).order_by('-created_at')
        return User.objects.filter(id=user.id)

    @action(detail=True, methods=['patch'], url_path='status')
    def update_status(self, request, pk=None):
        user_obj = self.get_object()
        new_status = request.data.get('status')
        if new_status not in ('active', 'inactive', 'suspended'):
            return Response({'detail': 'Invalid status.'}, status=status.HTTP_400_BAD_REQUEST)
        user_obj.status = new_status
        user_obj.save()
        return Response({'id': str(user_obj.id), 'status': user_obj.status})


# ============================================================================
# INCIDENT VIEWS
# ============================================================================

class IncidentViewSet(viewsets.ModelViewSet):
    """
    Incident management.
    - List/retrieve/create: any authenticated user (scoped by role/company)
    - Update: author, assigned agent, or HQ Admin
    - Assign: HQ Admin or Agent
    - Status patch: HQ Admin, Agent, or incident author
    - Comments: any authenticated user (internal comments: HQ Admin/Agent only)
    """

    def get_permissions(self):
        if self.action in ('update', 'partial_update', 'assign'):
            return [IsHQAdminOrAgent()]
        if self.action in ('destroy',):
            return [IsHQAdmin()]
        return [IsAuthenticated()]

    def get_serializer_class(self):
        if self.action == 'create':
            return IncidentCreateSerializer
        return IncidentSerializer

    def get_queryset(self):
        user = self.request.user
        qs = Incident.objects.select_related('company', 'submitted_by', 'assigned_to')
        if user.role in ('admin', 'agent', 'finance'):
            # HQ: allow optional ?company= filter for invoice dropdown etc.
            company_id = self.request.query_params.get('company')
            if company_id:
                qs = qs.filter(company=company_id)
            return qs.order_by('-created_at')
        if user.company:
            return qs.filter(company=user.company).order_by('-created_at')
        return qs.filter(submitted_by=user).order_by('-created_at')

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        # Return full incident data (not just the create fields)
        full = IncidentSerializer(serializer.instance, context={'request': request})
        headers = self.get_success_headers(full.data)
        return Response(full.data, status=status.HTTP_201_CREATED, headers=headers)

    def perform_create(self, serializer):
        user = self.request.user
        company = user.company

        # HQ admins/agents must pass an explicit company in the request body
        if not company and user.role in ('admin', 'agent'):
            company_id = self.request.data.get('company')
            if company_id:
                try:
                    company = Company.objects.get(id=company_id)
                except Company.DoesNotExist:
                    raise drf_serializers.ValidationError({'company': 'Company not found.'})

        if not company:
            # Client users must have a company linked to their account
            raise drf_serializers.ValidationError({
                'detail': (
                    'Your account is not linked to a company. '
                    'Please contact the HQ administrator to have your account configured.'
                )
            })

        ticket_id = f"INC-{str(uuid.uuid4())[:8].upper()}"
        incident = serializer.save(
            submitted_by=user,
            company=company,
            ticket_id=ticket_id,
        )
        incident.calculate_sla_deadlines()
        incident.save()
        _send_ticket_notification(incident, user)

    @action(detail=True, methods=['patch'], url_path='status')
    def update_status(self, request, pk=None):
        incident = self.get_object()
        user = request.user
        # Only HQ Admin, assigned agent, or incident author can update status
        if user.role not in ('admin', 'agent') and incident.submitted_by != user:
            return Response(
                {'detail': 'You do not have permission to update this incident status.'},
                status=status.HTTP_403_FORBIDDEN
            )
        new_status = request.data.get('status')
        if new_status not in ('open', 'in_progress', 'resolved', 'closed'):
            return Response({'detail': 'Invalid status.'}, status=status.HTTP_400_BAD_REQUEST)
        incident.status = new_status
        if new_status == 'resolved':
            incident.resolved_at = timezone.now()
        incident.save()
        return Response(IncidentSerializer(incident).data)

    @action(detail=True, methods=['patch'], url_path='assign')
    def assign(self, request, pk=None):
        incident = self.get_object()
        agent_id = request.data.get('agent_id')
        if not agent_id:
            return Response({'detail': 'agent_id is required.'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            agent = User.objects.get(id=agent_id, role__in=('admin', 'agent'))
        except User.DoesNotExist:
            return Response({'detail': 'Agent not found.'}, status=status.HTTP_404_NOT_FOUND)
        incident.assigned_to = agent
        if incident.status == StatusChoices.OPEN:
            incident.status = StatusChoices.IN_PROGRESS
        incident.save()
        return Response(IncidentSerializer(incident).data)

    @action(detail=True, methods=['get', 'post'], url_path='comments')
    def comments(self, request, pk=None):
        incident = self.get_object()
        if request.method == 'GET':
            user = request.user
            qs = incident.comments.select_related('author').all()
            # Non-HQ users can't see internal comments
            if user.role not in ('admin', 'agent'):
                qs = qs.filter(is_internal=False)
            return Response(IncidentCommentSerializer(qs, many=True).data)
        # POST: add a comment
        serializer = IncidentCommentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        # Only HQ Admin/Agent can post internal comments
        if serializer.validated_data.get('is_internal') and request.user.role not in ('admin', 'agent'):
            return Response(
                {'detail': 'Only HQ staff can post internal comments.'},
                status=status.HTTP_403_FORBIDDEN
            )
        serializer.save(incident=incident, author=request.user)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


# ============================================================================
# INVOICE VIEWS
# ============================================================================

class InvoiceViewSet(viewsets.ModelViewSet):
    """
    Invoice management.
    - List/retrieve: HQ staff (admin, agent, finance) OR clients (own company)
    - Create/update/delete: HQ staff only
    """
    serializer_class = InvoiceSerializer

    def get_permissions(self):
        if self.action in ('create', 'update', 'partial_update', 'destroy'):
            return [IsHQStaff()]
        return [IsAuthenticated()]

    def get_queryset(self):
        user = self.request.user
        qs = Invoice.objects.select_related('company').order_by('-created_at')
        if user.role in ('admin', 'agent', 'finance'):
            return qs
        # Clients only see their own company's invoices
        if user.company:
            return qs.filter(company=user.company)
        return qs.none()


# ============================================================================
# DASHBOARD
# ============================================================================

class DashboardMetricsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        qs = Incident.objects.all()
        if user.role not in ('admin', 'agent', 'finance'):
            if user.company:
                qs = qs.filter(company=user.company)
            else:
                qs = qs.filter(submitted_by=user)

        open_count = qs.filter(status='open').count()
        in_progress_count = qs.filter(status='in_progress').count()
        resolved_count = qs.filter(status='resolved').count()
        sla_breaches = qs.filter(is_sla_breached=True).count()
        recent_incidents = qs.select_related(
            'company', 'submitted_by', 'assigned_to'
        ).order_by('-created_at')[:10]

        return Response({
            'open_count': open_count,
            'in_progress_count': in_progress_count,
            'resolved_count': resolved_count,
            'sla_breach_count': sla_breaches,
            'total_active': open_count + in_progress_count,
            'recent_incidents': IncidentSerializer(recent_incidents, many=True).data,
        })


# ============================================================================
# NOTIFICATIONS
# ============================================================================

class NotificationsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = Notification.objects.filter(user=request.user).order_by('-created_at')[:50]
        data = [{
            'id': str(n.id),
            'type': n.notification_type,
            'title': n.title,
            'message': n.message,
            'is_read': n.is_read,
            'created_at': n.created_at.isoformat(),
            'incident_id': str(n.incident.id) if n.incident else None,
            'ticket_id': n.incident.ticket_id if n.incident else None,
        } for n in qs]
        unread = Notification.objects.filter(user=request.user, is_read=False).count()
        return Response({'notifications': data, 'unread_count': unread})

    def patch(self, request):
        if request.data.get('all'):
            Notification.objects.filter(user=request.user, is_read=False).update(
                is_read=True, read_at=timezone.now()
            )
        else:
            ids = request.data.get('ids', [])
            Notification.objects.filter(user=request.user, id__in=ids).update(
                is_read=True, read_at=timezone.now()
            )
        return Response({'detail': 'Marked as read.'})


# ============================================================================
# AUDIT LOG
# ============================================================================

class AuditLogView(APIView):
    permission_classes = [IsHQAdmin]

    def get(self, request):
        qs = AuditLog.objects.select_related('user').order_by('-created_at')[:200]
        data = [{
            'id': str(log.id),
            'user': log.user.email if log.user else 'System',
            'action': log.action,
            'model_name': log.model_name,
            'object_id': log.object_id,
            'old_values': log.old_values,
            'new_values': log.new_values,
            'ip_address': log.ip_address,
            'created_at': log.created_at.isoformat(),
        } for log in qs]
        return Response({'logs': data, 'total': len(data)})


# ============================================================================
# SLA BREACH MONITOR
# ============================================================================

class SLABreachListView(APIView):
    permission_classes = [IsHQAdminOrAgent]

    def get(self, request):
        qs = SLABreach.objects.select_related('incident', 'company').order_by('-breached_at')[:100]
        breaches = [{
            'id': str(b.id),
            'ticket_id': b.incident.ticket_id,
            'ticket_title': b.incident.title,
            'company': b.company.name,
            'breach_type': b.breach_type,
            'breached_at': b.breached_at.isoformat(),
            'time_over': b.time_over,
            'resolved': bool(b.resolved_at),
        } for b in qs]

        now = timezone.now()
        at_risk_qs = Incident.objects.filter(
            status__in=['open', 'in_progress'],
            is_sla_breached=False,
            response_deadline__isnull=False,
            response_deadline__gt=now,
        ).select_related('company')

        approaching = []
        for inc in at_risk_qs:
            hours_left = (inc.response_deadline - now).total_seconds() / 3600
            if hours_left < 4:
                approaching.append({
                    'ticket_id': inc.ticket_id,
                    'title': inc.title,
                    'company': inc.company.name if inc.company else '—',
                    'deadline': inc.response_deadline.isoformat(),
                    'hours_left': round(hours_left, 1),
                    'priority': inc.priority,
                })

        return Response({'breaches': breaches, 'approaching': approaching})


# ============================================================================
# PASSWORD RESET
# ============================================================================

import base64
from django.contrib.auth.tokens import PasswordResetTokenGenerator


class PasswordResetRequestView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        email = request.data.get('email', '').strip().lower()
        if not email:
            return Response({'detail': 'Email is required.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            user_obj = User.objects.get(email__iexact=email, is_active=True)
        except User.DoesNotExist:
            return Response({'detail': 'If that email exists, a reset link has been sent.'})

        generator = PasswordResetTokenGenerator()
        token = generator.make_token(user_obj)
        uid = base64.urlsafe_b64encode(str(user_obj.pk).encode()).decode()
        reset_url = f"{request.scheme}://{request.get_host()}/portal/password-reset/confirm/?uid={uid}&token={token}"

        html_body = f"""<!DOCTYPE html><html><body style="font-family:Arial,sans-serif;background:#f5f5f5;padding:32px 0">
<table width="600" cellpadding="0" cellspacing="0" style="background:#fff;border-radius:8px;margin:0 auto;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,.08)">
<tr><td style="background:#50181E;padding:24px 32px">
  <h1 style="margin:0;color:#B38F43;font-size:20px;font-weight:700;letter-spacing:1px">REHUMILE TMW</h1>
  <p style="margin:4px 0 0;color:rgba(255,255,255,.8);font-size:12px">Password Reset Request</p>
</td></tr>
<tr><td style="padding:32px">
  <p style="color:#333;font-size:15px">Hi <strong>{user_obj.first_name or user_obj.email}</strong>,</p>
  <p style="color:#555;font-size:14px;line-height:1.7">You requested a password reset for your Rehumile Portal account.
  Click the button below to set a new password. This link expires in <strong>24 hours</strong>.</p>
  <div style="text-align:center;margin:28px 0">
    <a href="{reset_url}" style="background:#50181E;color:#fff;padding:14px 32px;border-radius:6px;text-decoration:none;font-weight:700;font-size:15px">Reset My Password</a>
  </div>
  <p style="color:#888;font-size:12px">If you didn't request this, you can safely ignore this email.</p>
</td></tr>
<tr><td style="background:#f9f9f9;padding:14px 32px;border-top:1px solid #eee;text-align:center">
  <p style="margin:0;color:#bbb;font-size:11px">Rehumile TMW IMS &bull; noreply@rehumile.co.za</p>
</td></tr>
</table></body></html>"""

        try:
            msg = EmailMultiAlternatives(
                subject='Password Reset — Rehumile TMW Portal',
                body=f'Reset your password by visiting: {reset_url}',
                from_email=django_settings.DEFAULT_FROM_EMAIL,
                to=[user_obj.email],
            )
            msg.attach_alternative(html_body, 'text/html')
            msg.send(fail_silently=False)
        except Exception as exc:
            import logging
            logging.getLogger('ims.email').error('Password reset email failed for %s: %s', user_obj.email, exc)

        return Response({'detail': 'If that email exists, a reset link has been sent.'})


class PasswordResetConfirmView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        uid = request.data.get('uid', '')
        token = request.data.get('token', '')
        new_password = request.data.get('new_password', '')

        if not uid or not token or not new_password:
            return Response(
                {'detail': 'uid, token and new_password are required.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        if len(new_password) < 8:
            return Response(
                {'detail': 'Password must be at least 8 characters.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            pk = base64.urlsafe_b64decode(uid.encode() + b'==').decode()
            user_obj = User.objects.get(pk=pk)
        except Exception:
            return Response({'detail': 'Invalid reset link.'}, status=status.HTTP_400_BAD_REQUEST)

        generator = PasswordResetTokenGenerator()
        if not generator.check_token(user_obj, token):
            return Response(
                {'detail': 'Reset link has expired or is invalid.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        user_obj.set_password(new_password)
        user_obj.save()
        return Response({'detail': 'Password reset successfully. You can now sign in.'})


# ============================================================================
# INCIDENT ATTACHMENTS
# ============================================================================

import os
from django.core.files.storage import default_storage


class IncidentAttachmentView(APIView):
    permission_classes = [IsAuthenticated]

    def _get_incident(self, incident_id, user):
        try:
            inc = Incident.objects.get(id=incident_id)
        except Incident.DoesNotExist:
            return None, Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        if user.role not in ('admin', 'agent', 'finance'):
            if not user.company or inc.company != user.company:
                return None, Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        return inc, None

    def get(self, request, incident_id):
        inc, err = self._get_incident(incident_id, request.user)
        if err:
            return err
        attachments = IncidentAttachment.objects.filter(incident=inc)
        data = [{
            'id': str(a.id),
            'file_name': a.file_name,
            'file_size': a.file_size,
            'file_type': a.file_type,
            'uploaded_by': a.uploaded_by.email if a.uploaded_by else None,
            'created_at': a.created_at.isoformat(),
        } for a in attachments]
        return Response({'attachments': data})

    def post(self, request, incident_id):
        inc, err = self._get_incident(incident_id, request.user)
        if err:
            return err
        uploaded = request.FILES.get('file')
        if not uploaded:
            return Response({'detail': 'No file provided.'}, status=status.HTTP_400_BAD_REQUEST)
        if uploaded.size > 10 * 1024 * 1024:
            return Response(
                {'detail': 'File size exceeds 10 MB limit.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        safe_name = os.path.basename(uploaded.name)
        save_path = f'attachments/{incident_id}/{safe_name}'
        stored_path = default_storage.save(save_path, uploaded)
        att = IncidentAttachment.objects.create(
            incident=inc,
            file_name=safe_name,
            file_path=stored_path,
            file_size=uploaded.size,
            file_type=uploaded.content_type or '',
            uploaded_by=request.user,
        )
        return Response({
            'id': str(att.id),
            'file_name': att.file_name,
            'file_size': att.file_size,
            'file_type': att.file_type,
            'created_at': att.created_at.isoformat(),
        }, status=status.HTTP_201_CREATED)

# ============================================================================
# WORKSHOP — JOB CARDS
# ============================================================================

def _jc_serial():
    last = JobCard.objects.order_by("-created_at").first()
    if not last or not last.job_number.startswith("JC-"):
        return "JC-0001"
    try:
        n = int(last.job_number.split("-")[1]) + 1
    except (IndexError, ValueError):
        n = 1
    return f"JC-{n:04d}"


class JobCardListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        u = request.user
        qs = JobCard.objects.select_related("company", "technician", "invoice", "created_by")
        if u.role == "technician":
            qs = qs.filter(technician=u)
        elif u.role == "client":
            qs = qs.filter(company=u.company)
        status_filter = request.GET.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter)
        data = [{
            "id": str(j.id),
            "job_number": j.job_number,
            "customer_name": j.customer_name,
            "customer_phone": j.customer_phone,
            "customer_email": j.customer_email,
            "company": j.company.name if j.company else None,
            "device_type": j.device_type,
            "device_brand": j.device_brand,
            "device_model": j.device_model,
            "serial_number": j.serial_number,
            "status": j.status,
            "technician": f"{j.technician.first_name} {j.technician.last_name}".strip() if j.technician else None,
            "invoice_number": j.invoice.invoice_number if j.invoice else None,
            "created_at": j.created_at.isoformat(),
            "updated_at": j.updated_at.isoformat(),
        } for j in qs[:200]]
        return Response({"results": data, "count": len(data)})

    def post(self, request):
        u = request.user
        if u.role not in ("admin", "agent", "technician", "cashier"):
            return Response({"detail": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)
        d = request.data
        required = ["customer_name", "device_type", "serial_number", "physical_condition", "initial_diagnosis"]
        for f in required:
            if not d.get(f, "").strip():
                return Response({"detail": f"{f} is required."}, status=status.HTTP_400_BAD_REQUEST)
        jc = JobCard.objects.create(
            job_number=_jc_serial(),
            customer_name=d["customer_name"].strip(),
            customer_phone=d.get("customer_phone", "").strip(),
            customer_email=d.get("customer_email", "").strip(),
            device_type=d["device_type"].strip(),
            device_brand=d.get("device_brand", "").strip(),
            device_model=d.get("device_model", "").strip(),
            serial_number=d["serial_number"].strip(),
            physical_condition=d["physical_condition"].strip(),
            initial_diagnosis=d["initial_diagnosis"].strip(),
            technician_id=d.get("technician") or None,
            created_by=u,
        )
        return Response({"id": str(jc.id), "job_number": jc.job_number}, status=status.HTTP_201_CREATED)


class JobCardDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def _get(self, pk, user):
        try:
            jc = JobCard.objects.select_related("company", "technician", "invoice").get(pk=pk)
        except Exception:
            return None, Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        if user.role == "technician" and jc.technician != user:
            return None, Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return jc, None

    def get(self, request, pk):
        jc, err = self._get(pk, request.user)
        if err:
            return err
        return Response({
            "id": str(jc.id),
            "job_number": jc.job_number,
            "customer_name": jc.customer_name,
            "customer_phone": jc.customer_phone,
            "customer_email": jc.customer_email,
            "company": jc.company.name if jc.company else None,
            "device_type": jc.device_type,
            "device_brand": jc.device_brand,
            "device_model": jc.device_model,
            "serial_number": jc.serial_number,
            "physical_condition": jc.physical_condition,
            "initial_diagnosis": jc.initial_diagnosis,
            "final_diagnosis": jc.final_diagnosis,
            "technician_notes": jc.technician_notes,
            "status": jc.status,
            "technician_id": str(jc.technician.id) if jc.technician else None,
            "technician_name": f"{jc.technician.first_name} {jc.technician.last_name}".strip() if jc.technician else None,
            "invoice_id": str(jc.invoice.id) if jc.invoice else None,
            "invoice_number": jc.invoice.invoice_number if jc.invoice else None,
            "created_at": jc.created_at.isoformat(),
            "updated_at": jc.updated_at.isoformat(),
        })

    def patch(self, request, pk):
        jc, err = self._get(pk, request.user)
        if err:
            return err
        d = request.data
        new_status = d.get("status")
        if new_status == "paid_released":
            if not jc.invoice or jc.invoice.status != "paid":
                return Response(
                    {"detail": "Hardware release requires a fully paid linked invoice."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        for field in ("final_diagnosis", "technician_notes"):
            if field in d:
                setattr(jc, field, d[field])
        if new_status:
            jc.status = new_status
            if new_status == "paid_released":
                from django.utils import timezone as tz
                jc.completed_at = tz.now()
        if "technician" in d:
            try:
                jc.technician = User.objects.get(pk=d["technician"]) if d["technician"] else None
            except User.DoesNotExist:
                pass
        if request.user.role in ("admin", "agent") and "invoice" in d and d["invoice"]:
            try:
                jc.invoice = Invoice.objects.get(pk=d["invoice"])
            except Invoice.DoesNotExist:
                return Response({"detail": "Invoice not found."}, status=status.HTTP_400_BAD_REQUEST)
        jc.save()
        return Response({"detail": "Updated.", "status": jc.status})


# ============================================================================
# WORKSHOP — INVENTORY
# ============================================================================

class InventoryListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = InventoryItem.objects.filter(is_deleted=False)
        if request.GET.get("type"):
            qs = qs.filter(item_type=request.GET["type"])
        low_stock_only = request.GET.get("low_stock")
        data = []
        for item in qs:
            if low_stock_only and not item.is_low_stock:
                continue
            data.append({
                "id": str(item.id),
                "item_type": item.item_type,
                "name": item.name,
                "category": item.category,
                "serial_number": item.serial_number,
                "quantity_on_hand": item.quantity_on_hand,
                "reorder_level": item.reorder_level,
                "unit_cost": str(item.unit_cost),
                "selling_price": str(item.selling_price),
                "deployment_status": item.deployment_status,
                "is_low_stock": item.is_low_stock,
                "purchase_date": item.purchase_date.isoformat() if item.purchase_date else None,
            })
        return Response({"results": data, "count": len(data)})

    def post(self, request):
        if request.user.role not in ("admin", "agent"):
            return Response({"detail": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)
        d = request.data
        if not d.get("name", "").strip():
            return Response({"detail": "name is required."}, status=status.HTTP_400_BAD_REQUEST)
        item = InventoryItem.objects.create(
            item_type=d.get("item_type", "consumable"),
            name=d["name"].strip(),
            description=d.get("description", "").strip(),
            category=d.get("category", "").strip(),
            serial_number=d.get("serial_number", "").strip(),
            quantity_on_hand=int(d.get("quantity_on_hand", 0)),
            reorder_level=int(d.get("reorder_level", 5)),
            unit_cost=d.get("unit_cost", 0),
            selling_price=d.get("selling_price", 0),
            deployment_status=d.get("deployment_status", "active"),
        )
        return Response({"id": str(item.id), "name": item.name}, status=status.HTTP_201_CREATED)


class StockTransactionView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        u = request.user
        if u.role not in ("admin", "agent", "technician"):
            return Response({"detail": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)
        d = request.data
        try:
            item = InventoryItem.objects.get(pk=d.get("item_id"))
        except InventoryItem.DoesNotExist:
            return Response({"detail": "Item not found."}, status=status.HTTP_404_NOT_FOUND)
        txn_type = d.get("transaction_type", "out")
        qty = int(d.get("quantity", 0))
        if qty <= 0:
            return Response({"detail": "Quantity must be positive."}, status=status.HTTP_400_BAD_REQUEST)
        if txn_type == "out":
            ref = d.get("reference", "").strip()
            if not ref:
                return Response({"detail": "A Job Card or Invoice reference is required for stock deductions."}, status=status.HTTP_400_BAD_REQUEST)
            if item.quantity_on_hand < qty:
                return Response({"detail": "Insufficient stock."}, status=status.HTTP_400_BAD_REQUEST)
            item.quantity_on_hand -= qty
        elif txn_type == "in":
            item.quantity_on_hand += qty
        else:
            item.quantity_on_hand = max(0, item.quantity_on_hand + qty)
        item.save()
        jc = None
        if d.get("job_card_id"):
            try:
                jc = JobCard.objects.get(pk=d["job_card_id"])
            except JobCard.DoesNotExist:
                pass
        StockTransaction.objects.create(
            item=item,
            transaction_type=txn_type,
            quantity=qty,
            unit_cost=d.get("unit_cost", item.unit_cost),
            reference=d.get("reference", "").strip(),
            job_card=jc,
            performed_by=u,
            notes=d.get("notes", "").strip(),
        )
        return Response({"detail": "Stock updated.", "quantity_on_hand": item.quantity_on_hand}, status=status.HTTP_201_CREATED)


# ============================================================================
# CASH MANAGEMENT
# ============================================================================

class ShiftLogView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if request.user.role not in ("admin", "cashier", "finance"):
            return Response({"detail": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)
        qs = ShiftLog.objects.select_related("opened_by", "closed_by").order_by("-date")[:30]
        data = [{
            "id": str(s.id),
            "date": s.date.isoformat(),
            "opened_by": f"{s.opened_by.first_name} {s.opened_by.last_name}".strip() if s.opened_by else None,
            "opening_float": str(s.opening_float),
            "opened_at": s.opened_at.isoformat() if s.opened_at else None,
            "closed_by": f"{s.closed_by.first_name} {s.closed_by.last_name}".strip() if s.closed_by else None,
            "physical_cash_total": str(s.physical_cash_total) if s.physical_cash_total is not None else None,
            "card_total": str(s.card_total) if s.card_total is not None else None,
            "eft_total": str(s.eft_total) if s.eft_total is not None else None,
            "system_total": str(s.system_total) if s.system_total is not None else None,
            "variance": str(s.variance) if s.variance is not None else None,
            "closed_at": s.closed_at.isoformat() if s.closed_at else None,
            "notes": s.notes,
            "is_closed": s.is_closed,
        } for s in qs]
        return Response({"results": data})

    def post(self, request):
        u = request.user
        if u.role not in ("admin", "cashier", "finance"):
            return Response({"detail": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)
        d = request.data
        action = d.get("action", "open")
        from datetime import date as _date
        today = _date.today()
        if action == "open":
            if ShiftLog.objects.filter(date=today).exists():
                return Response({"detail": "A shift is already open for today."}, status=status.HTTP_400_BAD_REQUEST)
            if not d.get("opening_float"):
                return Response({"detail": "opening_float is required."}, status=status.HTTP_400_BAD_REQUEST)
            shift = ShiftLog.objects.create(
                date=today,
                opened_by=u,
                opening_float=d["opening_float"],
                opened_at=timezone.now(),
            )
            return Response({"id": str(shift.id), "date": shift.date.isoformat()}, status=status.HTTP_201_CREATED)
        elif action == "close":
            try:
                shift = ShiftLog.objects.get(date=today, is_closed=False)
            except ShiftLog.DoesNotExist:
                return Response({"detail": "No open shift found for today."}, status=status.HTTP_404_NOT_FOUND)
            from django.db.models import Sum
            cash_total = float(d.get("physical_cash_total") or 0)
            card_total_v = float(d.get("card_total") or 0)
            eft_total_v = float(d.get("eft_total") or 0)
            sys_total = float(CashTransaction.objects.filter(shift=shift).aggregate(t=Sum("amount"))["t"] or 0)
            physical_total = cash_total + card_total_v + eft_total_v
            shift.physical_cash_total = cash_total
            shift.card_total = card_total_v
            shift.eft_total = eft_total_v
            shift.system_total = sys_total
            shift.variance = physical_total - sys_total
            shift.closed_by = u
            shift.closed_at = timezone.now()
            shift.notes = d.get("notes", "")
            shift.is_closed = True
            shift.save()
            return Response({"detail": "Shift closed.", "variance": str(shift.variance)})
        return Response({"detail": "action must be open or close."}, status=status.HTTP_400_BAD_REQUEST)


class CashTransactionListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if request.user.role not in ("admin", "cashier", "finance"):
            return Response({"detail": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)
        qs = CashTransaction.objects.select_related("performed_by", "invoice", "job_card").order_by("-created_at")[:200]
        if request.GET.get("stream"):
            qs = qs.filter(cash_flow_stream=request.GET["stream"])
        data = [{
            "id": str(t.id),
            "amount": str(t.amount),
            "payment_method": t.payment_method,
            "cash_flow_stream": t.cash_flow_stream,
            "description": t.description,
            "invoice_number": t.invoice.invoice_number if t.invoice else None,
            "job_number": t.job_card.job_number if t.job_card else None,
            "performed_by": t.performed_by.email if t.performed_by else None,
            "created_at": t.created_at.isoformat(),
        } for t in qs]
        return Response({"results": data})

    def post(self, request):
        u = request.user
        if u.role not in ("admin", "cashier", "finance"):
            return Response({"detail": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)
        d = request.data
        if not d.get("amount") or not d.get("payment_method") or not d.get("description"):
            return Response({"detail": "amount, payment_method, description are required."}, status=status.HTTP_400_BAD_REQUEST)
        from datetime import date as _date
        shift = ShiftLog.objects.filter(date=_date.today(), is_closed=False).first()
        invoice = None
        if d.get("invoice_id"):
            invoice = Invoice.objects.filter(pk=d["invoice_id"]).first()
        job_card = None
        if d.get("job_card_id"):
            job_card = JobCard.objects.filter(pk=d["job_card_id"]).first()
        txn = CashTransaction.objects.create(
            shift=shift, invoice=invoice, job_card=job_card,
            amount=d["amount"],
            payment_method=d["payment_method"],
            cash_flow_stream=d.get("cash_flow_stream", "ocf"),
            description=d["description"].strip(),
            performed_by=u,
        )
        return Response({"id": str(txn.id)}, status=status.HTTP_201_CREATED)


# ============================================================================
# VOUCHERS
# ============================================================================

class VoucherView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if request.user.role not in ("admin", "cashier", "finance"):
            return Response({"detail": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)
        qs = Voucher.objects.select_related("sold_by").order_by("-created_at")[:200]
        if request.GET.get("status"):
            qs = qs.filter(status=request.GET["status"])
        data = [{
            "id": str(v.id),
            "voucher_code": v.voucher_code,
            "duration_hours": v.duration_hours,
            "selling_price": str(v.selling_price),
            "status": v.status,
            "sold_by": v.sold_by.email if v.sold_by else None,
            "sold_at": v.sold_at.isoformat() if v.sold_at else None,
        } for v in qs]
        return Response({"results": data})

    def post(self, request):
        u = request.user
        d = request.data
        action = d.get("action", "create")
        if action == "create":
            if u.role not in ("admin",):
                return Response({"detail": "Only admins can create vouchers."}, status=status.HTTP_403_FORBIDDEN)
            import secrets, string as _string
            code = d.get("voucher_code") or "".join(secrets.choice(_string.ascii_uppercase + _string.digits) for _ in range(8))
            v = Voucher.objects.create(
                voucher_code=code,
                duration_hours=int(d.get("duration_hours", 24)),
                selling_price=d.get("selling_price", 0),
            )
            return Response({"id": str(v.id), "voucher_code": v.voucher_code}, status=status.HTTP_201_CREATED)
        elif action == "sell":
            if u.role not in ("admin", "cashier"):
                return Response({"detail": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)
            try:
                v = Voucher.objects.get(pk=d.get("voucher_id"), status="available")
            except Voucher.DoesNotExist:
                return Response({"detail": "Voucher not available."}, status=status.HTTP_400_BAD_REQUEST)
            from datetime import date as _date
            shift = ShiftLog.objects.filter(date=_date.today(), is_closed=False).first()
            txn = CashTransaction.objects.create(
                shift=shift, amount=v.selling_price,
                payment_method=d.get("payment_method", "cash"),
                cash_flow_stream="ocf",
                description=f"Voucher sale {v.voucher_code} ({v.duration_hours}h)",
                performed_by=u,
            )
            v.status = "sold"
            v.sold_by = u
            v.sold_at = timezone.now()
            v.cash_transaction = txn
            v.save()
            return Response({"detail": "Voucher sold.", "voucher_code": v.voucher_code})
        return Response({"detail": "action must be create or sell."}, status=status.HTTP_400_BAD_REQUEST)


# ============================================================================
# FINANCIAL ANALYTICS
# ============================================================================

class FinancialAnalyticsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if request.user.role not in ("admin", "finance"):
            return Response({"detail": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)
        from django.db.models import Sum
        from datetime import date as _date
        import calendar

        today = _date.today()
        month_start = today.replace(day=1)
        month_end = today.replace(day=calendar.monthrange(today.year, today.month)[1])

        inv_qs = Invoice.objects.filter(billing_period_start__gte=month_start, billing_period_start__lte=month_end)
        revenue = float(inv_qs.filter(status="paid").aggregate(t=Sum("total_amount"))["t"] or 0)
        pending = float(inv_qs.filter(status="sent").aggregate(t=Sum("total_amount"))["t"] or 0)
        overdue = float(inv_qs.filter(status="overdue").aggregate(t=Sum("total_amount"))["t"] or 0)

        txn_qs = CashTransaction.objects.filter(created_at__date__gte=month_start, created_at__date__lte=month_end)
        ocf = float(txn_qs.filter(cash_flow_stream="ocf").aggregate(t=Sum("amount"))["t"] or 0)
        icf = float(txn_qs.filter(cash_flow_stream="icf").aggregate(t=Sum("amount"))["t"] or 0)
        fcf = float(txn_qs.filter(cash_flow_stream="fcf").aggregate(t=Sum("amount"))["t"] or 0)

        expenses = float(PurchaseSlip.objects.filter(purchase_date__gte=month_start, purchase_date__lte=month_end).aggregate(t=Sum("amount"))["t"] or 0)

        gross_profit = revenue - expenses
        gpm = round((gross_profit / revenue * 100) if revenue else 0, 1)

        jc_counts = {s: JobCard.objects.filter(created_at__date__gte=month_start, status=s).count()
                     for s in ("logged", "in_progress", "awaiting_parts", "ready", "paid_released")}

        from django.db.models import F as _F
        low_stock = list(InventoryItem.objects.filter(
            item_type="consumable", is_deleted=False,
            quantity_on_hand__lte=_F("reorder_level"),
        ).values("id", "name", "quantity_on_hand", "reorder_level")[:10])

        return Response({
            "period": {"start": month_start.isoformat(), "end": month_end.isoformat()},
            "revenue": {"paid": revenue, "pending": pending, "overdue": overdue},
            "cash_flows": {"ocf": ocf, "icf": icf, "fcf": fcf},
            "expenses": expenses,
            "gross_profit": gross_profit,
            "gpm_percent": gpm,
            "job_cards": jc_counts,
            "low_stock_alerts": low_stock,
        })


# ============================================================================
# SARS COMPLIANCE STAGING VIEWS
# ============================================================================

from .models import (
    CompliancePeriod, SupplierSlipOCR, PurchaseSlip,
    Employee, PayrollEntry, LeaveBalance, LeaveRequest,
    TaskTemplate, TaskCompletion,
    Invoice, CashTransaction, ShiftLog,
)
from decimal import Decimal
import datetime as _dt
import zipfile
import io


def _paye_monthly(gross_monthly: float) -> float:
    """2025/2026 SARS progressive PAYE — returns monthly PAYE amount."""
    annual = gross_monthly * 12
    threshold = 95_750
    if annual <= threshold:
        return 0.0
    brackets = [
        (237_100,  0,       0.18),
        (370_500,  237_100, 0.26),
        (512_800,  370_500, 0.31),
        (673_000,  512_800, 0.36),
        (857_900,  673_000, 0.39),
        (1_817_000, 857_900, 0.41),
        (float('inf'), 1_817_000, 0.45),
    ]
    base_taxes = [0, 42_678, 77_362, 121_475, 179_147, 251_258, 644_489]
    annual_paye = 0.0
    for i, (upper, lower, rate) in enumerate(brackets):
        if annual <= upper:
            annual_paye = base_taxes[i] + (annual - lower) * rate
            break
    annual_paye = max(annual_paye - 17_235, 0)  # primary rebate
    return round(annual_paye / 12, 2)


def _uif_monthly(gross_monthly: float) -> float:
    """1% UIF — employee portion, capped at R1,476/month."""
    return round(min(gross_monthly * 0.01, 1476.0), 2)


class CompliancePeriodListView(APIView):
    """List all periods or create a new one for the current month."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        periods = CompliancePeriod.objects.all().values(
            'id', 'period_label', 'period_start', 'period_end', 'status',
            'field1_standard_rated_sales', 'field4_output_tax',
            'field14_capital_goods_input', 'field15_non_capital_input',
            'net_vat_liability', 'total_paye', 'total_uif_employee',
            'total_uif_employer', 'audit_ready', 'audit_flags',
        )
        return Response(list(periods))

    def post(self, request):
        label = request.data.get('period_label')  # e.g. "2026-06"
        if not label:
            today = timezone.now().date()
            label = today.strftime('%Y-%m')
        if CompliancePeriod.objects.filter(period_label=label).exists():
            return Response({'error': f'Period {label} already exists.'}, status=400)
        year, month = int(label[:4]), int(label[5:7])
        import calendar
        start = _dt.date(year, month, 1)
        end = _dt.date(year, month, calendar.monthrange(year, month)[1])
        period = CompliancePeriod.objects.create(
            period_label=label, period_start=start, period_end=end,
        )
        return Response({'id': str(period.id), 'period_label': period.period_label}, status=201)


class CompliancePeriodDetailView(APIView):
    """Retrieve one period, trigger state transitions, or build audit zip."""
    permission_classes = [IsAuthenticated]

    def _get_period(self, pk):
        try:
            return CompliancePeriod.objects.get(pk=pk)
        except CompliancePeriod.DoesNotExist:
            return None

    def get(self, request, pk):
        p = self._get_period(pk)
        if not p:
            return Response({'error': 'Not found.'}, status=404)
        data = {
            'id': str(p.id), 'period_label': p.period_label,
            'period_start': p.period_start, 'period_end': p.period_end,
            'status': p.status,
            'field1_standard_rated_sales': float(p.field1_standard_rated_sales),
            'field4_output_tax': float(p.field4_output_tax),
            'field14_capital_goods_input': float(p.field14_capital_goods_input),
            'field15_non_capital_input': float(p.field15_non_capital_input),
            'net_vat_liability': float(p.net_vat_liability),
            'total_paye': float(p.total_paye), 'total_uif_employee': float(p.total_uif_employee),
            'total_uif_employer': float(p.total_uif_employer),
            'audit_flags': p.audit_flags, 'audit_ready': p.audit_ready,
            'finalized_at': p.finalized_at,
        }
        return Response(data)

    def post(self, request, pk):
        """State transitions: action=stage|finalize|recalculate"""
        p = self._get_period(pk)
        if not p:
            return Response({'error': 'Not found.'}, status=404)
        action_name = request.data.get('action')

        if action_name == 'recalculate':
            self._recalculate(p)
            return Response({'status': p.status, 'message': 'Aggregates recalculated.'})

        if action_name == 'stage':
            if p.status != 'active':
                return Response({'error': 'Can only stage an active period.'}, status=400)
            self._recalculate(p)
            p.status = 'staging'
            p.staged_at = timezone.now()
            p.save()
            return Response({'status': 'staging'})

        if action_name == 'finalize':
            if p.status != 'staging':
                return Response({'error': 'Period must be in staging before finalizing.'}, status=400)
            self._recalculate(p)
            p.status = 'finalized'
            p.finalized_at = timezone.now()
            p.finalized_by = request.user
            p.save()
            return Response({'status': 'finalized'})

        return Response({'error': 'Unknown action.'}, status=400)

    def _recalculate(self, period):
        """Aggregate VAT and payroll figures into the period record."""
        from django.db.models import Sum
        invoices = Invoice.objects.filter(
            created_at__date__gte=period.period_start,
            created_at__date__lte=period.period_end,
        )
        total_gross = float(invoices.aggregate(t=Sum('total_amount'))['t'] or 0)
        field1 = round(total_gross / 1.15, 2)
        field4 = round(total_gross - field1, 2)

        # Input tax — from validated OCR slips
        capital_qs = SupplierSlipOCR.objects.filter(
            compliance_period=period, is_capital_goods=True, ocr_status='valid',
        )
        non_cap_qs = SupplierSlipOCR.objects.filter(
            compliance_period=period, is_capital_goods=False, ocr_status='valid',
        )
        field14 = float(capital_qs.aggregate(t=Sum('stated_vat_amount'))['t'] or 0)
        field15 = float(non_cap_qs.aggregate(t=Sum('stated_vat_amount'))['t'] or 0)
        net_vat = round(field4 - field14 - field15, 2)

        # EMP201 aggregates from payroll
        payroll_qs = PayrollEntry.objects.filter(compliance_period=period)
        total_paye = float(payroll_qs.aggregate(t=Sum('paye_amount'))['t'] or 0)
        total_uif_e = float(payroll_qs.aggregate(t=Sum('uif_employee'))['t'] or 0)
        total_uif_er = float(payroll_qs.aggregate(t=Sum('uif_employer'))['t'] or 0)

        # Audit flags
        flags = []
        pending_ocr = SupplierSlipOCR.objects.filter(
            compliance_period=period, ocr_status__in=['pending', 'invalid'],
        ).count()
        if pending_ocr:
            flags.append(f'{pending_ocr} supplier slip(s) have unresolved OCR flags and cannot be claimed.')

        period.field1_standard_rated_sales = Decimal(str(field1))
        period.field4_output_tax = Decimal(str(field4))
        period.field14_capital_goods_input = Decimal(str(field14))
        period.field15_non_capital_input = Decimal(str(field15))
        period.net_vat_liability = Decimal(str(net_vat))
        period.total_paye = Decimal(str(total_paye))
        period.total_uif_employee = Decimal(str(total_uif_e))
        period.total_uif_employer = Decimal(str(total_uif_er))
        period.audit_flags = flags
        period.audit_ready = (pending_ocr == 0)
        period.save()


class VAT201View(APIView):
    """Return VAT201 reconciliation data for a given period."""
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        try:
            p = CompliancePeriod.objects.get(pk=pk)
        except CompliancePeriod.DoesNotExist:
            return Response({'error': 'Not found.'}, status=404)
        slips = SupplierSlipOCR.objects.filter(compliance_period=p).values(
            'id', 'supplier_vat_number', 'invoice_date', 'gross_amount',
            'stated_vat_amount', 'is_capital_goods', 'ocr_status', 'ocr_flags',
        )
        return Response({
            'period': {'label': p.period_label, 'status': p.status},
            'vat201': {
                'field1': float(p.field1_standard_rated_sales),
                'field4': float(p.field4_output_tax),
                'field14': float(p.field14_capital_goods_input),
                'field15': float(p.field15_non_capital_input),
                'net_vat_liability': float(p.net_vat_liability),
            },
            'input_slips': list(slips),
            'audit_ready': p.audit_ready,
            'audit_flags': p.audit_flags,
        })


class SupplierSlipOCRView(APIView):
    """Upload and validate supplier slips for OCR intake."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        period_id = request.query_params.get('period_id')
        qs = SupplierSlipOCR.objects.select_related('purchase_slip', 'compliance_period')
        if period_id:
            qs = qs.filter(compliance_period_id=period_id)
        data = list(qs.values(
            'id', 'supplier_vat_number', 'invoice_date', 'gross_amount',
            'stated_vat_amount', 'is_capital_goods', 'ocr_status', 'ocr_flags',
            'compliance_period__period_label', 'purchase_slip__reference_number',
        ))
        return Response(data)

    def post(self, request):
        """Create or update OCR record for a purchase slip."""
        slip_id = request.data.get('purchase_slip_id')
        period_id = request.data.get('compliance_period_id')
        try:
            slip = PurchaseSlip.objects.get(pk=slip_id)
        except PurchaseSlip.DoesNotExist:
            return Response({'error': 'Purchase slip not found.'}, status=404)

        ocr, _ = SupplierSlipOCR.objects.get_or_create(purchase_slip=slip)
        ocr.supplier_vat_number = request.data.get('supplier_vat_number', '')
        ocr.invoice_date = request.data.get('invoice_date') or None
        ocr.gross_amount = Decimal(str(request.data.get('gross_amount', 0)))
        ocr.stated_vat_amount = Decimal(str(request.data.get('stated_vat_amount', 0)))
        ocr.is_capital_goods = request.data.get('is_capital_goods', False)
        if period_id:
            try:
                ocr.compliance_period = CompliancePeriod.objects.get(pk=period_id)
            except CompliancePeriod.DoesNotExist:
                pass
        flags = ocr.validate_vat()
        ocr.save()
        return Response({
            'id': str(ocr.id),
            'ocr_status': ocr.ocr_status,
            'ocr_flags': ocr.ocr_flags,
            'validation_flags': flags,
        }, status=201)

    def patch(self, request, pk=None):
        """Manual override — mark as manually verified."""
        try:
            ocr = SupplierSlipOCR.objects.get(pk=pk)
        except SupplierSlipOCR.DoesNotExist:
            return Response({'error': 'Not found.'}, status=404)
        ocr.ocr_status = 'manual'
        ocr.validated_at = timezone.now()
        ocr.validated_by = request.user
        ocr.save()
        return Response({'ocr_status': ocr.ocr_status})


# ============================================================================
# HR & PAYROLL VIEWS
# ============================================================================

class EmployeeListView(APIView):
    """POPIA-restricted employee list — admin/owner only."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = Employee.objects.filter(is_active=True).values(
            'id', 'employee_number', 'first_name', 'last_name',
            'job_title', 'employment_type', 'gross_monthly_salary',
            'start_date', 'is_active',
        )
        return Response(list(qs))

    def post(self, request):
        data = request.data
        emp = Employee.objects.create(
            employee_number=data.get('employee_number', f"EMP{Employee.objects.count()+1:04d}"),
            first_name=data.get('first_name', ''),
            last_name=data.get('last_name', ''),
            id_number=data.get('id_number', ''),
            tax_reference_number=data.get('tax_reference_number', ''),
            bank_name=data.get('bank_name', ''),
            bank_account_number=data.get('bank_account_number', ''),
            bank_branch_code=data.get('bank_branch_code', ''),
            physical_address=data.get('physical_address', ''),
            contact_number=data.get('contact_number', ''),
            next_of_kin_name=data.get('next_of_kin_name', ''),
            next_of_kin_contact=data.get('next_of_kin_contact', ''),
            employment_type=data.get('employment_type', 'full_time'),
            job_title=data.get('job_title', ''),
            gross_monthly_salary=Decimal(str(data.get('gross_monthly_salary', 0))),
            hourly_rate=Decimal(str(data.get('hourly_rate', 0))),
            scheduled_hours_per_week=Decimal(str(data.get('scheduled_hours_per_week', 40))),
            start_date=data.get('start_date') or None,
        )
        # Seed BCEA leave balances
        today = timezone.now().date()
        cycle_start = _dt.date(today.year, 1, 1)
        for lt, days in [('annual', 21), ('sick', 30), ('family', 3)]:
            LeaveBalance.objects.create(
                employee=emp, leave_type=lt, total_days=days,
                used_days=0, cycle_start=cycle_start,
            )
        return Response({'id': str(emp.id), 'employee_number': emp.employee_number}, status=201)


class EmployeeDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        try:
            emp = Employee.objects.get(pk=pk)
        except Employee.DoesNotExist:
            return Response({'error': 'Not found.'}, status=404)
        balances = list(emp.leave_balances.values('leave_type', 'total_days', 'used_days', 'cycle_start'))
        for b in balances:
            b['available_days'] = float(b['total_days']) - float(b['used_days'])
        return Response({
            'id': str(emp.id), 'employee_number': emp.employee_number,
            'first_name': emp.first_name, 'last_name': emp.last_name,
            'id_number': emp.id_number, 'tax_reference_number': emp.tax_reference_number,
            'bank_name': emp.bank_name, 'bank_account_number': emp.bank_account_number,
            'bank_branch_code': emp.bank_branch_code,
            'physical_address': emp.physical_address, 'contact_number': emp.contact_number,
            'next_of_kin_name': emp.next_of_kin_name, 'next_of_kin_contact': emp.next_of_kin_contact,
            'employment_type': emp.employment_type, 'job_title': emp.job_title,
            'gross_monthly_salary': float(emp.gross_monthly_salary),
            'hourly_rate': float(emp.hourly_rate),
            'scheduled_hours_per_week': float(emp.scheduled_hours_per_week),
            'start_date': emp.start_date, 'is_active': emp.is_active,
            'leave_balances': balances,
        })

    def patch(self, request, pk):
        try:
            emp = Employee.objects.get(pk=pk)
        except Employee.DoesNotExist:
            return Response({'error': 'Not found.'}, status=404)
        allowed = [
            'first_name', 'last_name', 'id_number', 'tax_reference_number',
            'bank_name', 'bank_account_number', 'bank_branch_code',
            'physical_address', 'contact_number', 'next_of_kin_name',
            'next_of_kin_contact', 'employment_type', 'job_title',
            'gross_monthly_salary', 'hourly_rate', 'scheduled_hours_per_week',
            'start_date', 'end_date', 'is_active',
        ]
        for field in allowed:
            if field in request.data:
                setattr(emp, field, request.data[field])
        emp.save()
        return Response({'id': str(emp.id)})


class PayrollView(APIView):
    """Calculate and freeze payroll for a compliance period."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        period_id = request.query_params.get('period_id')
        qs = PayrollEntry.objects.select_related('employee', 'compliance_period')
        if period_id:
            qs = qs.filter(compliance_period_id=period_id)
        data = list(qs.values(
            'id', 'employee__first_name', 'employee__last_name', 'employee__employee_number',
            'compliance_period__period_label',
            'gross_salary', 'overtime_amount', 'total_gross',
            'paye_amount', 'uif_employee', 'uif_employer', 'net_pay',
            'is_frozen', 'payslip_emailed',
        ))
        return Response(data)

    def post(self, request):
        """Calculate payroll for all active employees in a period."""
        period_id = request.data.get('period_id')
        try:
            period = CompliancePeriod.objects.get(pk=period_id)
        except CompliancePeriod.DoesNotExist:
            return Response({'error': 'Period not found.'}, status=404)
        if period.status == 'finalized':
            return Response({'error': 'Period is finalized — cannot recalculate.'}, status=400)

        employees = Employee.objects.filter(is_active=True)
        created, updated = 0, 0
        for emp in employees:
            gross = float(emp.gross_monthly_salary)
            paye = _paye_monthly(gross)
            uif_e = _uif_monthly(gross)
            uif_er = uif_e  # employer matches
            net = round(gross - paye - uif_e, 2)
            entry, is_new = PayrollEntry.objects.update_or_create(
                employee=emp, compliance_period=period,
                defaults={
                    'gross_salary': Decimal(str(gross)),
                    'total_gross': Decimal(str(gross)),
                    'paye_amount': Decimal(str(paye)),
                    'uif_employee': Decimal(str(uif_e)),
                    'uif_employer': Decimal(str(uif_er)),
                    'net_pay': Decimal(str(net)),
                    'is_frozen': False,
                },
            )
            if is_new:
                created += 1
            else:
                updated += 1
        return Response({'calculated': created + updated, 'created': created, 'updated': updated})

    def patch(self, request, pk=None):
        """Freeze a payroll entry."""
        try:
            entry = PayrollEntry.objects.get(pk=pk)
        except PayrollEntry.DoesNotExist:
            return Response({'error': 'Not found.'}, status=404)
        entry.is_frozen = True
        entry.save()
        return Response({'is_frozen': True})


class EMP201View(APIView):
    """EMP201 staging dashboard aggregates + UIF CSV export."""
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        try:
            period = CompliancePeriod.objects.get(pk=pk)
        except CompliancePeriod.DoesNotExist:
            return Response({'error': 'Not found.'}, status=404)
        entries = PayrollEntry.objects.filter(compliance_period=period).select_related('employee')
        rows = []
        for e in entries:
            rows.append({
                'employee_number': e.employee.employee_number,
                'name': f"{e.employee.first_name} {e.employee.last_name}",
                'gross': float(e.total_gross),
                'paye': float(e.paye_amount),
                'uif_employee': float(e.uif_employee),
                'uif_employer': float(e.uif_employer),
                'net_pay': float(e.net_pay),
            })
        return Response({
            'period': period.period_label,
            'emp201': {
                'total_paye': float(period.total_paye),
                'total_uif_employee': float(period.total_uif_employee),
                'total_uif_employer': float(period.total_uif_employer),
                'total_uif_combined': float(period.total_uif_employee) + float(period.total_uif_employer),
            },
            'payroll_rows': rows,
        })

    def get_csv(self, request, pk):
        """Download UIF declaration CSV."""
        from django.http import HttpResponse as _HR
        try:
            period = CompliancePeriod.objects.get(pk=pk)
        except CompliancePeriod.DoesNotExist:
            return Response({'error': 'Not found.'}, status=404)
        lines = ['EmployeeNumber,Name,GrossEarnings,UIFEmployee,UIFEmployer']
        for e in PayrollEntry.objects.filter(compliance_period=period).select_related('employee'):
            lines.append(
                f"{e.employee.employee_number},"
                f"{e.employee.first_name} {e.employee.last_name},"
                f"{float(e.total_gross):.2f},"
                f"{float(e.uif_employee):.2f},"
                f"{float(e.uif_employer):.2f}"
            )
        resp = _HR('\n'.join(lines), content_type='text/csv')
        resp['Content-Disposition'] = f'attachment; filename="UIF_{period.period_label}.csv"'
        return resp


class LeaveRequestView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = LeaveRequest.objects.select_related('employee').order_by('-created_at')
        emp_id = request.query_params.get('employee_id')
        if emp_id:
            qs = qs.filter(employee_id=emp_id)
        data = list(qs.values(
            'id', 'employee__first_name', 'employee__last_name',
            'leave_type', 'start_date', 'end_date', 'days_requested',
            'reason', 'status', 'reviewed_at', 'created_at',
        ))
        return Response(data)

    def post(self, request):
        data = request.data
        try:
            emp = Employee.objects.get(pk=data.get('employee_id'))
        except Employee.DoesNotExist:
            return Response({'error': 'Employee not found.'}, status=404)
        req = LeaveRequest.objects.create(
            employee=emp,
            leave_type=data.get('leave_type', 'annual'),
            start_date=data.get('start_date'),
            end_date=data.get('end_date'),
            days_requested=Decimal(str(data.get('days_requested', 1))),
            reason=data.get('reason', ''),
        )
        return Response({'id': str(req.id), 'status': req.status}, status=201)

    def patch(self, request, pk=None):
        """Approve or reject a leave request."""
        try:
            req = LeaveRequest.objects.get(pk=pk)
        except LeaveRequest.DoesNotExist:
            return Response({'error': 'Not found.'}, status=404)
        action_name = request.data.get('action')  # 'approve' or 'reject'
        if action_name == 'approve':
            req.status = 'approved'
            req.reviewed_by = request.user
            req.review_note = request.data.get('note', '')
            req.reviewed_at = timezone.now()
            req.save()
            # Deduct from balance
            try:
                balance = LeaveBalance.objects.get(
                    employee=req.employee, leave_type=req.leave_type,
                )
                balance.used_days += req.days_requested
                balance.save()
            except LeaveBalance.DoesNotExist:
                pass
        elif action_name == 'reject':
            req.status = 'rejected'
            req.reviewed_by = request.user
            req.review_note = request.data.get('note', '')
            req.reviewed_at = timezone.now()
            req.save()
        else:
            return Response({'error': 'action must be approve or reject.'}, status=400)
        return Response({'status': req.status})


# ============================================================================
# OPERATIONAL PLAYBOOK VIEWS
# ============================================================================

class TaskTemplateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        role = request.query_params.get('role')
        freq = request.query_params.get('frequency')
        qs = TaskTemplate.objects.filter(is_active=True)
        if role:
            qs = qs.filter(role=role)
        if freq:
            qs = qs.filter(frequency=freq)
        return Response(list(qs.values(
            'id', 'role', 'frequency', 'title', 'description',
            'link_url', 'is_blocking', 'sort_order',
        )))

    def post(self, request):
        t = TaskTemplate.objects.create(
            role=request.data.get('role', 'admin'),
            frequency=request.data.get('frequency', 'daily_morning'),
            title=request.data.get('title', ''),
            description=request.data.get('description', ''),
            link_url=request.data.get('link_url', ''),
            is_blocking=request.data.get('is_blocking', False),
            sort_order=request.data.get('sort_order', 0),
        )
        return Response({'id': str(t.id), 'title': t.title}, status=201)


class TaskCompletionView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        date_ref = request.query_params.get('date', timezone.now().date().isoformat())
        role = request.query_params.get('role')
        templates = TaskTemplate.objects.filter(is_active=True)
        if role:
            templates = templates.filter(role=role)
        completed_ids = set(
            TaskCompletion.objects.filter(
                completed_by=request.user, date_ref=date_ref,
            ).values_list('task_template_id', flat=True)
        )
        data = []
        for t in templates:
            data.append({
                'id': str(t.id), 'role': t.role, 'frequency': t.frequency,
                'title': t.title, 'description': t.description,
                'link_url': t.link_url, 'is_blocking': t.is_blocking,
                'sort_order': t.sort_order,
                'completed': str(t.id) in [str(x) for x in completed_ids],
            })
        return Response(data)

    def post(self, request):
        """Mark a task complete — writes immutable audit entry."""
        task_id = request.data.get('task_id')
        date_ref = request.data.get('date', timezone.now().date().isoformat())
        try:
            template = TaskTemplate.objects.get(pk=task_id)
        except TaskTemplate.DoesNotExist:
            return Response({'error': 'Task not found.'}, status=404)
        _, created = TaskCompletion.objects.get_or_create(
            task_template=template,
            completed_by=request.user,
            date_ref=date_ref,
            defaults={'note': request.data.get('note', '')},
        )
        return Response({'created': created, 'task': template.title}, status=201)


# ============================================================================
# WEBSITE CONTENT MANAGEMENT VIEWS
# ============================================================================

from .models import ServicePrice, WebsiteContent


class ServicePriceView(APIView):
    """CRUD for service prices displayed on the public website."""

    def get_permissions(self):
        if self.request.method == 'GET':
            return [AllowAny()]
        return [IsAuthenticated()]

    def get(self, request):
        qs = ServicePrice.objects.filter(is_active=True)
        featured_only = request.query_params.get('featured')
        if featured_only:
            qs = qs.filter(is_featured=True)
        data = list(qs.values(
            'id', 'name', 'category', 'description', 'price', 'unit',
            'is_featured', 'is_active', 'display_order',
        ))
        return Response(data)

    def post(self, request):
        d = request.data
        sp = ServicePrice.objects.create(
            name=d.get('name', ''),
            category=d.get('category', 'it_support'),
            description=d.get('description', ''),
            price=d.get('price', 0),
            unit=d.get('unit', 'per visit'),
            is_featured=d.get('is_featured', False),
            is_active=d.get('is_active', True),
            display_order=d.get('display_order', 0),
        )
        return Response({'id': str(sp.id), 'name': sp.name}, status=201)

    def patch(self, request, pk=None):
        try:
            sp = ServicePrice.objects.get(pk=pk)
        except ServicePrice.DoesNotExist:
            return Response({'error': 'Not found.'}, status=404)
        allowed = ['name', 'category', 'description', 'price', 'unit',
                   'is_featured', 'is_active', 'display_order']
        for field in allowed:
            if field in request.data:
                setattr(sp, field, request.data[field])
        sp.save()
        return Response({'id': str(sp.id)})

    def delete(self, request, pk=None):
        try:
            sp = ServicePrice.objects.get(pk=pk)
        except ServicePrice.DoesNotExist:
            return Response({'error': 'Not found.'}, status=404)
        sp.delete()
        return Response(status=204)


class WebsiteContentView(APIView):
    """Manage editable text blocks for public website pages."""

    def get_permissions(self):
        if self.request.method == 'GET':
            return [AllowAny()]
        return [IsAuthenticated()]

    def get(self, request):
        section = request.query_params.get('section')
        qs = WebsiteContent.objects.all()
        if section:
            qs = qs.filter(section=section)
        data = list(qs.values('id', 'section', 'key', 'label', 'value', 'updated_at'))
        return Response(data)

    def post(self, request):
        """Upsert a content block by key."""
        key = request.data.get('key', '')
        obj, created = WebsiteContent.objects.update_or_create(
            key=key,
            defaults={
                'section': request.data.get('section', 'hero'),
                'label': request.data.get('label', key),
                'value': request.data.get('value', ''),
                'updated_by': request.user,
            },
        )
        return Response({'id': str(obj.id), 'key': obj.key, 'created': created}, status=201 if created else 200)

    def patch(self, request, pk=None):
        try:
            obj = WebsiteContent.objects.get(pk=pk)
        except WebsiteContent.DoesNotExist:
            return Response({'error': 'Not found.'}, status=404)
        obj.value = request.data.get('value', obj.value)
        obj.label = request.data.get('label', obj.label)
        obj.updated_by = request.user
        obj.save()
        return Response({'id': str(obj.id)})



# ============================================================================
# PAYFAST PAYMENT INTEGRATION
# ============================================================================

import uuid as uuid_lib
import logging
from .models import Payment, Invoice
from .payfast import (
    build_payment_data, validate_itn,
    PAYFAST_PROCESS_URL, PAYFAST_SANDBOX,
)

pf_logger = logging.getLogger("ims.payfast")


def _base_url(request):
    scheme = request.scheme
    return f"{scheme}://{request.get_host()}"


class PayFastInitiateView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        invoice_id = request.data.get("invoice_id")
        if not invoice_id:
            return Response({"detail": "invoice_id required."}, status=400)
        try:
            invoice = Invoice.objects.get(pk=invoice_id)
        except Invoice.DoesNotExist:
            return Response({"detail": "Invoice not found."}, status=404)

        user = request.user
        if user.role == "client" and user.company != invoice.company:
            return Response({"detail": "Access denied."}, status=403)

        amount = float(invoice.total_amount)
        inv_ref = getattr(invoice, "invoice_number", None) or str(invoice.id)[:8]
        reference = f"INV-{inv_ref[:8].upper()}-{uuid_lib.uuid4().hex[:6].upper()}"
        item_name = f"Invoice {inv_ref}"

        Payment.objects.create(
            reference=reference, invoice=invoice, user=user,
            amount=amount, item_name=item_name,
            first_name=user.first_name, last_name=user.last_name,
            email_address=user.email, service_type="invoice", status="pending",
        )

        base = _base_url(request)
        pf_data = build_payment_data(
            reference=reference, amount=amount, item_name=item_name,
            first_name=user.first_name, last_name=user.last_name, email=user.email,
            return_url=f"{base}/portal/client/billing/?payment=success&ref={reference}",
            cancel_url=f"{base}/portal/client/billing/?payment=cancelled&ref={reference}",
            notify_url=f"{base}/portal/api/payments/payfast-notify/",
        )
        return Response({"reference": reference, "payfast_url": PAYFAST_PROCESS_URL, "fields": pf_data})


class PayFastPublicInitiateView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        first_name = request.data.get("first_name", "").strip()
        last_name = request.data.get("last_name", "").strip()
        email = request.data.get("email", "").strip()
        service_name = request.data.get("service_name", "").strip()
        amount = request.data.get("amount")

        if not first_name or not email or not service_name or not amount:
            return Response({"detail": "first_name, email, service_name and amount required."}, status=400)
        try:
            amount = float(amount)
            if amount <= 0:
                raise ValueError
        except (ValueError, TypeError):
            return Response({"detail": "Invalid amount."}, status=400)

        reference = f"WEB-{uuid_lib.uuid4().hex[:10].upper()}"
        Payment.objects.create(
            reference=reference, amount=amount, item_name=service_name[:100],
            first_name=first_name, last_name=last_name, email_address=email,
            service_type=service_name, status="pending",
        )

        base = _base_url(request)
        pf_data = build_payment_data(
            reference=reference, amount=amount, item_name=service_name[:100],
            first_name=first_name, last_name=last_name, email=email,
            return_url=f"{base}/payment/success/?ref={reference}",
            cancel_url=f"{base}/payment/cancel/?ref={reference}",
            notify_url=f"{base}/portal/api/payments/payfast-notify/",
        )
        return Response({"reference": reference, "payfast_url": PAYFAST_PROCESS_URL, "fields": pf_data})


class PayFastITNView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        post_data = request.POST.dict()
        pf_logger.info("PayFast ITN received: %s", post_data)
        is_valid, reason = validate_itn(post_data)
        if not is_valid:
            pf_logger.warning("PayFast ITN rejected: %s", reason)
            return HttpResponse(status=400)

        reference = post_data.get("m_payment_id", "")
        pf_payment_id = post_data.get("pf_payment_id", "")
        payment_status_str = post_data.get("payment_status", "").upper()

        try:
            payment = Payment.objects.get(reference=reference)
        except Payment.DoesNotExist:
            return HttpResponse(status=200)

        payment.pf_payment_id = pf_payment_id
        payment.raw_itn = str(post_data)

        if payment_status_str == "COMPLETE":
            payment.status = "complete"
            if payment.invoice:
                invoice = payment.invoice
                invoice.status = "paid"
                invoice.save(update_fields=["status"])
        elif payment_status_str in ("FAILED", "CANCELLED"):
            payment.status = payment_status_str.lower()

        payment.save()
        return HttpResponse(status=200)


class PaymentListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        if user.role in ("admin", "hq", "technician"):
            qs = Payment.objects.select_related("user", "invoice").all()
        else:
            qs = Payment.objects.filter(user=user)
        status_filter = request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter)
        data = [
            {
                "id": str(p.id),
                "reference": p.reference,
                "pf_payment_id": p.pf_payment_id,
                "invoice_id": str(p.invoice.id) if p.invoice else None,
                "invoice_number": getattr(p.invoice, "invoice_number", None) if p.invoice else None,
                "user_name": f"{p.first_name} {p.last_name}".strip(),
                "email": p.email_address,
                "amount": float(p.amount),
                "item_name": p.item_name,
                "service_type": p.service_type,
                "status": p.status,
                "created_at": p.created_at.isoformat(),
            }
            for p in qs[:200]
        ]
        return Response(data)


# ============================================================================
# INVOICE EMAIL REMINDER
# ============================================================================

class InvoiceReminderView(APIView):
    """HQ: send a payment reminder email to the client contact for an invoice."""
    permission_classes = [IsAuthenticated]

    def post(self, request, invoice_id):
        if request.user.role not in ("admin", "hq", "technician"):
            return Response({"detail": "HQ access required."}, status=403)

        try:
            invoice = Invoice.objects.select_related("company", "incident").get(pk=invoice_id)
        except Invoice.DoesNotExist:
            return Response({"detail": "Invoice not found."}, status=404)

        # Resolve recipient email — prefer custom override, then company email, then incident requester
        to_email = request.data.get("email", "").strip()
        if not to_email and invoice.company:
            to_email = (invoice.company.billing_email or invoice.company.contact_email or "").strip()
        if not to_email and invoice.incident:
            to_email = getattr(invoice.incident.requester, "email", "") if invoice.incident.requester else ""
        if not to_email:
            return Response({"detail": "No email address found for this invoice. Provide one in the request body."}, status=400)

        invoice_number = invoice.invoice_number or str(invoice.id)[:8].upper()
        amount = float(invoice.total_amount or 0)
        due_date = invoice.due_date.strftime("%d %B %Y") if invoice.due_date else "As soon as possible"
        description = invoice.description or invoice.notes or "IT Support Services"

        # Build a payment initiation link (auto-creates payment record)
        base = request.scheme + "://" + request.get_host()
        pay_link = f"{base}/portal/client/billing/"

        # HTML email body
        html_body = f"""
<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;font-family:'Segoe UI',Arial,sans-serif;background:#f4f4f7">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f4f4f7;padding:32px 0">
    <tr><td align="center">
      <table width="600" cellpadding="0" cellspacing="0" style="background:#ffffff;border-radius:12px;overflow:hidden;box-shadow:0 4px 24px rgba(0,0,0,0.08)">

        <!-- Header -->
        <tr><td style="background:#50181E;padding:28px 40px">
          <table width="100%" cellpadding="0" cellspacing="0">
            <tr>
              <td>
                <p style="margin:0;color:#B38F43;font-size:22px;font-weight:900;letter-spacing:-0.5px">REHUMILE TMW</p>
                <p style="margin:4px 0 0;color:rgba(255,255,255,0.7);font-size:12px">IT Services &amp; Solutions</p>
              </td>
              <td align="right">
                <p style="margin:0;color:rgba(255,255,255,0.5);font-size:11px;text-transform:uppercase;letter-spacing:1px">Invoice Reminder</p>
              </td>
            </tr>
          </table>
        </td></tr>

        <!-- Body -->
        <tr><td style="padding:36px 40px">
          <h2 style="margin:0 0 8px;color:#1a1a1a;font-size:24px">Payment Reminder</h2>
          <p style="margin:0 0 24px;color:#666;font-size:15px">You have an outstanding invoice with Rehumile TMW. Please review the details below and complete your payment at your earliest convenience.</p>

          <!-- Invoice card -->
          <table width="100%" cellpadding="0" cellspacing="0" style="background:#fafafa;border:1.5px solid #e8e8e8;border-radius:10px;margin-bottom:28px">
            <tr><td style="padding:20px 24px;border-bottom:1px solid #e8e8e8">
              <p style="margin:0;font-size:11px;text-transform:uppercase;letter-spacing:1px;color:#999;font-weight:700">Invoice Details</p>
            </td></tr>
            <tr><td style="padding:20px 24px">
              <table width="100%" cellpadding="0" cellspacing="0">
                <tr>
                  <td style="padding-bottom:12px">
                    <p style="margin:0;font-size:12px;color:#999">Invoice Number</p>
                    <p style="margin:4px 0 0;font-size:16px;font-weight:700;color:#1a1a1a">{invoice_number}</p>
                  </td>
                  <td style="padding-bottom:12px" align="right">
                    <p style="margin:0;font-size:12px;color:#999">Amount Due</p>
                    <p style="margin:4px 0 0;font-size:24px;font-weight:900;color:#50181E">R {amount:,.2f}</p>
                  </td>
                </tr>
                <tr>
                  <td>
                    <p style="margin:0;font-size:12px;color:#999">Description</p>
                    <p style="margin:4px 0 0;font-size:14px;color:#444">{description}</p>
                  </td>
                  <td align="right">
                    <p style="margin:0;font-size:12px;color:#999">Due Date</p>
                    <p style="margin:4px 0 0;font-size:14px;font-weight:600;color:#c0392b">{due_date}</p>
                  </td>
                </tr>
              </table>
            </td></tr>
          </table>

          <!-- CTA Button -->
          <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:24px">
            <tr><td align="center">
              <a href="{pay_link}" style="display:inline-block;background:linear-gradient(135deg,#B38F43,#d4ac58);color:#ffffff;font-size:16px;font-weight:700;text-decoration:none;padding:16px 40px;border-radius:10px;box-shadow:0 6px 20px rgba(179,143,67,0.35)">
                Pay Invoice Now &rarr;
              </a>
            </td></tr>
          </table>

          <p style="margin:0;color:#888;font-size:13px;text-align:center">If you have already made payment, please disregard this notice.</p>
        </td></tr>

        <!-- Footer -->
        <tr><td style="background:#f8f8f8;padding:20px 40px;border-top:1px solid #ececec">
          <table width="100%" cellpadding="0" cellspacing="0">
            <tr>
              <td style="color:#aaa;font-size:12px">
                <p style="margin:0">Rehumile TMW &bull; Jozini, KwaZulu-Natal</p>
                <p style="margin:4px 0 0">📞 068 397 3484 &bull; ✉️ infor@rehumile.co.za</p>
              </td>
              <td align="right">
                <a href="{base}/" style="color:#50181E;font-size:12px;text-decoration:none;font-weight:600">www.rehumile.co.za</a>
              </td>
            </tr>
          </table>
        </td></tr>

      </table>
    </td></tr>
  </table>
</body>
</html>
"""

        plain_body = f"""Invoice Reminder — Rehumile TMW

Invoice Number: {invoice_number}
Amount Due: R {amount:,.2f}
Due Date: {due_date}
Description: {description}

Pay via your client portal: {pay_link}

Questions? Call 068 397 3484 or email infor@rehumile.co.za
"""

        try:
            from django.core.mail import EmailMultiAlternatives
            msg = EmailMultiAlternatives(
                subject=f"Payment Reminder — Invoice {invoice_number} | Rehumile TMW",
                body=plain_body,
                from_email=django_settings.DEFAULT_FROM_EMAIL,
                to=[to_email],
                cc=["finance@rehumile.co.za"],
            )
            msg.attach_alternative(html_body, "text/html")
            msg.send()
        except Exception as exc:
            pf_logger.error("Invoice reminder email failed: %s", exc)
            return Response({"detail": f"Email failed: {exc}"}, status=500)

        return Response({"detail": f"Reminder sent to {to_email}", "email": to_email})

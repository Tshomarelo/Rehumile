from django.shortcuts import render
from django.utils import timezone
from django.contrib.auth import get_user_model
from django.core.mail import EmailMultiAlternatives
from django.conf import settings as django_settings
from rest_framework import viewsets, status, generics
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.decorators import action
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth import authenticate
import uuid


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
        msg.send(fail_silently=True)
    except Exception:
        pass

from .models import (
    Company, UserProfile, Incident, IncidentComment,
    SLAConfig, StatusChoices, Invoice
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
        if not company and user.role == 'admin':
            company_id = self.request.data.get('company')
            if company_id:
                company = Company.objects.get(id=company_id)

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

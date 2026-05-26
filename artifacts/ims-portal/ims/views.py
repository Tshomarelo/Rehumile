from django.shortcuts import render
from django.utils import timezone
from django.contrib.auth import get_user_model
from rest_framework import viewsets, status, generics
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.decorators import action
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth import authenticate
import uuid

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
            return qs.order_by('-created_at')
        if user.company:
            return qs.filter(company=user.company).order_by('-created_at')
        return qs.filter(submitted_by=user).order_by('-created_at')

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
    - List/retrieve: HQ staff (admin, agent, finance)
    - Create/update/delete: HQ staff
    """
    serializer_class = InvoiceSerializer

    def get_permissions(self):
        return [IsHQStaff()]

    def get_queryset(self):
        return Invoice.objects.select_related('company').order_by('-created_at')


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

from rest_framework import serializers
from django.contrib.auth import get_user_model
from django.utils.text import slugify
from .models import Company, UserProfile, Incident, IncidentComment, Invoice

User = get_user_model()


class CompanySerializer(serializers.ModelSerializer):
    slug = serializers.SlugField(required=False, allow_blank=True)

    class Meta:
        model = Company
        fields = [
            'id', 'name', 'slug', 'description',
            'contact_person', 'contact_email', 'contact_phone',
            'billing_email', 'sla_type', 'status',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def _unique_slug(self, name, exclude_id=None):
        base = slugify(name)
        slug, n = base, 1
        while True:
            qs = Company.objects.filter(slug=slug)
            if exclude_id:
                qs = qs.exclude(id=exclude_id)
            if not qs.exists():
                return slug
            slug = f"{base}-{n}"
            n += 1

    def create(self, validated_data):
        if not validated_data.get('slug'):
            validated_data['slug'] = self._unique_slug(validated_data['name'])
        return super().create(validated_data)

    def update(self, instance, validated_data):
        if not validated_data.get('slug'):
            name = validated_data.get('name', instance.name)
            validated_data['slug'] = self._unique_slug(name, exclude_id=instance.id)
        return super().update(instance, validated_data)


class UserSerializer(serializers.ModelSerializer):
    company_name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            'id', 'email', 'first_name', 'last_name',
            'role', 'status', 'company', 'company_name',
            'is_active', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def get_company_name(self, obj):
        return obj.company.name if obj.company else None


class UserCreateSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=8)

    class Meta:
        model = User
        fields = [
            'email', 'first_name', 'last_name',
            'role', 'company', 'password',
        ]

    def create(self, validated_data):
        password = validated_data.pop('password')
        email = validated_data['email']
        user = User(**validated_data)
        user.username = email
        user.set_password(password)
        user.save()
        return user


class IncidentCommentSerializer(serializers.ModelSerializer):
    author_name = serializers.SerializerMethodField()
    author_email = serializers.SerializerMethodField()

    class Meta:
        model = IncidentComment
        fields = [
            'id', 'incident', 'author', 'author_name', 'author_email',
            'comment_text', 'is_internal', 'is_edited',
            'edited_at', 'created_at',
        ]
        read_only_fields = ['id', 'incident', 'author', 'created_at', 'is_edited', 'edited_at']

    def get_author_name(self, obj):
        if obj.author:
            return f"{obj.author.first_name} {obj.author.last_name}".strip() or obj.author.email
        return 'Unknown'

    def get_author_email(self, obj):
        return obj.author.email if obj.author else None


class IncidentSerializer(serializers.ModelSerializer):
    company_name = serializers.SerializerMethodField()
    submitted_by_name = serializers.SerializerMethodField()
    assigned_to_name = serializers.SerializerMethodField()
    comment_count = serializers.SerializerMethodField()

    class Meta:
        model = Incident
        fields = [
            'id', 'ticket_id', 'title', 'description', 'category',
            'company', 'company_name',
            'submitted_by', 'submitted_by_name',
            'assigned_to', 'assigned_to_name',
            'status', 'priority', 'sla_type',
            'response_deadline', 'resolution_deadline',
            'is_sla_breached', 'is_escalated',
            'is_billable', 'hours_worked', 'billable_amount',
            'resolution_notes', 'resolved_at',
            'comment_count',
            'created_at', 'updated_at',
        ]
        read_only_fields = [
            'id', 'ticket_id', 'submitted_by', 'company',
            'is_sla_breached', 'created_at', 'updated_at',
        ]

    def get_company_name(self, obj):
        return obj.company.name if obj.company else None

    def get_submitted_by_name(self, obj):
        if obj.submitted_by:
            return f"{obj.submitted_by.first_name} {obj.submitted_by.last_name}".strip() or obj.submitted_by.email
        return None

    def get_assigned_to_name(self, obj):
        if obj.assigned_to:
            return f"{obj.assigned_to.first_name} {obj.assigned_to.last_name}".strip() or obj.assigned_to.email
        return None

    def get_comment_count(self, obj):
        return obj.comments.count()


class IncidentCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Incident
        fields = [
            'title', 'description', 'category',
            'priority', 'is_billable',
        ]


class InvoiceSerializer(serializers.ModelSerializer):
    company_name = serializers.SerializerMethodField()
    incident_ticket_id = serializers.SerializerMethodField()
    incident_title = serializers.SerializerMethodField()

    class Meta:
        model = Invoice
        fields = [
            'id', 'invoice_number', 'company', 'company_name',
            'incident', 'incident_ticket_id', 'incident_title',
            'billing_period_start', 'billing_period_end',
            'subtotal', 'tax_rate', 'tax_amount', 'total_amount',
            'ticket_count', 'hours_worked', 'status', 'notes',
            'due_date', 'payment_date', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'tax_amount', 'total_amount', 'created_at', 'updated_at',
                            'incident_ticket_id', 'incident_title']

    def get_company_name(self, obj):
        return obj.company.name if obj.company else None

    def get_incident_ticket_id(self, obj):
        return obj.incident.ticket_id if obj.incident else None

    def get_incident_title(self, obj):
        return obj.incident.title if obj.incident else None

    def _calc_totals(self, data):
        subtotal = data.get('subtotal', 0) or 0
        tax_rate = data.get('tax_rate', 0) or 0
        tax_amount = round(float(subtotal) * float(tax_rate) / 100, 2)
        data['tax_amount'] = tax_amount
        data['total_amount'] = round(float(subtotal) + tax_amount, 2)
        return data

    def create(self, validated_data):
        self._calc_totals(validated_data)
        return super().create(validated_data)

    def update(self, instance, validated_data):
        self._calc_totals(validated_data)
        return super().update(instance, validated_data)


class DashboardMetricsSerializer(serializers.Serializer):
    open_count = serializers.IntegerField()
    in_progress_count = serializers.IntegerField()
    resolved_count = serializers.IntegerField()
    sla_breach_count = serializers.IntegerField()
    total_active = serializers.IntegerField()
    recent_incidents = IncidentSerializer(many=True)

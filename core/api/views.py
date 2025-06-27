import djstripe.models as sm
import stripe
from core.api.permissions import IsManager
from core.api.serializers import (PaymentMethodSerializer, PlanSerializer,
                                  SubscriptionSerializer)
from django_countries import countries
from django.conf import settings
from django.utils import timezone
from datetime import timedelta
from djstripe.models import Customer, Subscription
from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from schools.models import School
import time


class ListCountries(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, format=None):
        """
        Return a list of all countries.
        """
        return Response(
            dict(zip(('code', 'name'), country)) for country in countries)


class PlanListAPIView(generics.ListAPIView):
    queryset = sm.Plan.objects.filter(active=True)
    serializer_class = PlanSerializer
    permission_classes = [IsManager]


# https://www.saaspegasus.com/guides/django-stripe-integrate/
class CreateCustomerSubscription(APIView):
    permission_classes = [IsManager]

    def post(self, request):
        try:
            user = request.user
            school = School.objects.get(pk=request.data.get('schoolId'))
            email = request.data.get('email')
            assert user.email == email
            assert school.manager == user

            # Disable all Stripe/payment logic
            # Option 1: Just create a dummy subscription object in your DB
            # Option 2: If you want to keep using djstripe, create a local Subscription

            # Example: Create a dummy subscription object (adjust as needed)
            from djstripe.models import Subscription

            # Create a dummy subscription if not exists
            if school.subscription is None:
                now = timezone.now()
                customer, _ = Customer.objects.get_or_create(
                    subscriber=user,
                    defaults={
                        "email": user.email,
                        "currency": "usd",
                        "livemode": False,
                    }
                )
                # Use timestamp for uniqueness
                dummy_id = f"dummy_sub_{school.id}_{int(time.time())}"
                subscription, created = Subscription.objects.get_or_create(
                    id=dummy_id,
                    defaults={
                        "customer": customer,
                        "status": "active",
                        "metadata": {"school": school.id},
                        "trial_end": None,
                        "start_date": now,
                        "current_period_start": now,
                        "current_period_end": now + timedelta(days=30),
                        "cancel_at_period_end": False,
                        "ended_at": None,
                        "canceled_at": None,
                        "plan": None,
                        "quantity": 1,
                    }
                )
                school.subscription = subscription
                school.save()
            else:
                subscription = school.subscription

            # Optionally, associate a dummy customer
            user.customer = None
            user.save()

            data = {
                'customer': None,
                'subscription': SubscriptionSerializer(subscription).data
            }
            return Response(data, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({'error': str(e)},
                            status=status.HTTP_400_BAD_REQUEST)


class UpdateSubscription(APIView):
    permission_classes = [IsManager]

    def post(self, request):
        try:
            stripe.api_key = settings.STRIPE_TEST_SECRET_KEY

            slug = request.data.get('slug')
            school = generics.get_object_or_404(School, slug=slug)
            sub_id = school.subscription.id
            price_id = request.data.get('price_id')

            subscription = stripe.Subscription.retrieve(sub_id)

            subscription = stripe.Subscription.modify(
                sub_id,
                cancel_at_period_end=False,
                proration_behavior='create_prorations',
                items=[{
                    'id': subscription['items']['data'][0].id,
                    'price': price_id,
                }]
            )
            djstripe_subscription = sm.Subscription.sync_from_stripe_data(
                subscription)

            # associate subscription awith the school
            school.subscription = djstripe_subscription
            school.save()

            serializer = SubscriptionSerializer(djstripe_subscription)

            return Response(serializer.data, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({'detail': e}, status=status.HTTP_400_BAD_REQUEST)


class CancelSubscription(APIView):
    permission_classes = [IsManager]

    def post(self, request):
        try:
            stripe.api_key = settings.STRIPE_TEST_SECRET_KEY
            slug = request.data.get('slug')
            school = generics.get_object_or_404(School, slug=slug)
            sub_id = school.subscription.id
            subscription = stripe.Subscription.modify(
                sub_id,
                cancel_at_period_end=True
            )
            djstripe_subscription = sm.Subscription.sync_from_stripe_data(
                subscription)

            # associate subscription awith the school
            school.subscription = djstripe_subscription
            school.save()

            serializer = SubscriptionSerializer(djstripe_subscription)

            return Response(serializer.data, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({'detail': e}, status=status.HTTP_400_BAD_REQUEST)


class ReactivateSubscription(APIView):
    permission_classes = [IsManager]

    def post(self, request):
        try:
            stripe.api_key = settings.STRIPE_TEST_SECRET_KEY
            slug = request.data.get('slug')
            school = generics.get_object_or_404(School, slug=slug)
            sub_id = school.subscription.id
            subscription = stripe.Subscription.modify(
                sub_id,
                cancel_at_period_end=True
            )
            subscription = stripe.Subscription.modify(
                sub_id,
                cancel_at_period_end=False,
            )
            djstripe_subscription = sm.Subscription.sync_from_stripe_data(
                subscription)

            # associate subscription awith the school
            school.subscription = djstripe_subscription
            school.save()

            serializer = SubscriptionSerializer(djstripe_subscription)

            return Response(serializer.data, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({'detail': e}, status=status.HTTP_400_BAD_REQUEST)


class RetrieveStripeSubscription(APIView):
    permission_classes = [IsManager]

    def post(self, request):
        sub_id = request.data.get('id')
        stripe.api_key = settings.STRIPE_TEST_SECRET_KEY
        subscription = stripe.Subscription.retrieve(sub_id)

        return Response(subscription, status=status.HTTP_200_OK)


class RetrieveDBSubscription(generics.RetrieveAPIView):
    queryset = sm.Subscription.objects.all()
    serializer_class = SubscriptionSerializer
    permission_classes = [IsManager]


class RetrievePaymentMethod(APIView):
    permission_classes = [IsManager]

    def post(self, request):
        try:
            user = request.user
            pm_id = (
                user.customer.invoice_settings['default_payment_method'])
            paymentMethod = generics.get_object_or_404(sm.PaymentMethod,
                                                       id=pm_id)
            serializer = PaymentMethodSerializer(paymentMethod)

            return Response(serializer.data, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({'detail': e}, status=status.HTTP_400_BAD_REQUEST)

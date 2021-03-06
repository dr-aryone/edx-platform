"""
Test entitlements tasks
"""

from __future__ import absolute_import

from datetime import datetime, timedelta

import mock
import pytz
from django.test import TestCase

from entitlements import tasks
from entitlements.models import CourseEntitlementPolicy
from entitlements.tests.factories import CourseEntitlementFactory
from openedx.core.djangolib.testing.utils import skip_unless_lms


def make_entitlement(expired=False):
    age = CourseEntitlementPolicy.DEFAULT_EXPIRATION_PERIOD_DAYS
    past_datetime = datetime.now(tz=pytz.UTC) - timedelta(days=age)
    expired_at = past_datetime if expired else None
    entitlement = CourseEntitlementFactory.create(created=past_datetime, expired_at=expired_at)
    return entitlement


def boom():
    raise Exception('boom')


@skip_unless_lms
class TestExpireOldEntitlementsTask(TestCase):
    """
    Tests for the 'expire_old_entitlements' method.
    """
    def test_checks_expiration(self):
        """
        Test that we actually do check expiration on each entitlement (happy path)
        """
        make_entitlement()
        make_entitlement()

        with mock.patch(
            'entitlements.models.CourseEntitlement.expired_at_datetime',
            new_callable=mock.PropertyMock
        ) as mock_datetime:
            tasks.expire_old_entitlements.delay(1, 3).get()

        self.assertEqual(mock_datetime.call_count, 2)

    def test_only_unexpired(self):
        """
        Verify that only unexpired entitlements are included
        """
        # Create an old expired and an old unexpired entitlement
        make_entitlement(expired=True)
        make_entitlement()

        with mock.patch(
            'entitlements.models.CourseEntitlement.expired_at_datetime',
            new_callable=mock.PropertyMock
        ) as mock_datetime:
            tasks.expire_old_entitlements.delay(1, 3).get()

        # Make sure only the unexpired one gets used
        self.assertEqual(mock_datetime.call_count, 1)

    def test_retry(self):
        """
        Test that we retry when an exception occurs while checking old
        entitlements.
        """
        make_entitlement()

        with mock.patch(
            'entitlements.models.CourseEntitlement.expired_at_datetime',
            new_callable=mock.PropertyMock,
            side_effect=boom
        ) as mock_datetime:
            task = tasks.expire_old_entitlements.delay(1, 2)

        self.assertRaises(Exception, task.get)
        self.assertEqual(mock_datetime.call_count, tasks.MAX_RETRIES + 1)


@skip_unless_lms
class TestExpireOldEntitlementsTaskIntegration(TestCase):
    """
    Tests for the 'expire_old_entitlements' method without mocking.
    """
    def test_actually_expired(self):
        """
        Integration test with CourseEntitlement to make sure we are calling the
        correct API.
        """
        entitlement = make_entitlement()

        # Sanity check
        self.assertIsNone(entitlement.expired_at)

        # Run enforcement
        tasks.expire_old_entitlements.delay(1, 2).get()
        entitlement.refresh_from_db()

        self.assertIsNotNone(entitlement.expired_at)

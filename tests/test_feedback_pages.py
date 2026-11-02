import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import database
with patch.object(database, 'init_db'):
    import app as application
from pymongo.errors import ConnectionFailure


class FeedbackPagesTest(unittest.TestCase):
    def setUp(self):
        self.client = application.app.test_client()

    def test_dashboard_displays_real_counts_and_registered_contacts(self):
        notes = [{'anon_id': 'Attendee#ABC', 'channel': 'WEB', 'category': 'FACILITIES',
                  'urgency': 'HIGH', 'raw_text': '<script>alert(1)</script>'}]
        with patch.object(application, 'get_all_feedback', return_value=notes), patch.object(application, 'guests_collection') as guests:
            guests.find.return_value = [{'name': 'Test Guest', 'phone': '+256700000000'}]
            response = self.client.get('/dashboard')
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('Test Guest', html)
        self.assertIn('Attendee#ABC', html)
        self.assertIn('&lt;script&gt;alert(1)&lt;/script&gt;', html)
        self.assertNotIn('/api/organizer/delete', html)
        self.assertNotIn('/api/organizer/reply', html)
        self.assertIn('customerMessageForm', html)
        self.assertIn("sendDashboardMessage('/announcements'", html)
        self.assertIn("sendDashboardMessage('/reminders'", html)

    def test_database_outage_still_renders_dashboard_warning(self):
        with patch.object(application, 'get_all_feedback', side_effect=ConnectionFailure()), patch.object(application, 'guests_collection', None):
            response = self.client.get('/feedback')
        self.assertEqual(response.status_code, 200)
        self.assertIn('Database is unavailable', response.get_data(as_text=True))

    def test_attendee_page_uses_real_submission_endpoint(self):
        response = self.client.get('/attendee')
        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn('/api/voice_web', html)
        self.assertIn('if (!response.ok)', html)
        self.assertNotIn('Stage speakers are cracking', html)


if __name__ == '__main__':
    unittest.main()

import unittest
import requests

class TestAuthEndpoints(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base_url = "http://localhost:5000/auth"
        cls.test_email = "test@example.com"
        cls.test_password = "securepassword123"

    def test_signup_login_flow(self):
        # Test signup
        signup_data = {
            "email": self.test_email,
            "password": self.test_password
        }
        signup_response = requests.post(f"{self.base_url}/signup", json=signup_data)
        self.assertEqual(signup_response.status_code, 201)
        
        # Test login
        login_data = {
            "email": self.test_email,
            "password": self.test_password
        }
        login_response = requests.post(f"{self.base_url}/login", json=login_data)
        self.assertEqual(login_response.status_code, 200)
        
        # Verify tokens received
        login_json = login_response.json()
        self.assertIn("access_token", login_json)
        self.assertIn("refresh_token", login_json)
        self.assertIn("user", login_json)

    def test_protected_endpoint(self):
        # First login to get token
        login_data = {
            "email": self.test_email,
            "password": self.test_password
        }
        login_response = requests.post(f"{self.base_url}/login", json=login_data)
        token = login_response.json()["access_token"]
        
        # Test protected endpoint
        headers = {"Authorization": f"Bearer {token}"}
        protected_response = requests.post(
            "http://localhost:5000/api/chat",
            json={"query": "test", "category": "all"},
            headers=headers
        )
        self.assertEqual(protected_response.status_code, 200)

if __name__ == "__main__":
    unittest.main()

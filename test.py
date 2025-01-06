import unittest
import os
from flask import json
from main import app

class ApiTestCase(unittest.TestCase):
    def setUp(self):
        self.app = app.test_client()
        self.app.testing = True

    def test_status(self):
        response = self.app.get('/api/status')
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.get_data(as_text=True))
        self.assertEqual(data['status'], 'OK')

    def test_get_txt_file(self):
        response = self.app.post('/api/get_txt_file', data={'file_path': 'megasoft/file.txt'})
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.get_data(as_text=True))
        self.assertIsInstance(data, list)

    def test_check_txt_file(self):
        response = self.app.post('/api/check_txt_file', data={'folder_path': 'megasoft'})
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.get_data(as_text=True))
        self.assertIn('exists', data)
        self.assertIn('data', data)
        self.assertIsInstance(data['data'], list)

    def test_clear_txt_file(self):
        response = self.app.post('/api/clear_txt_file', data={'folder_path': 'megasoft'})
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.get_data(as_text=True))
        self.assertEqual(data['status'], 'OK')
    def test_restart_service(self):
        response = self.app.post('/api/restart_service')
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.get_data(as_text=True))
        self.assertEqual(data['status'], 'OK')

if __name__ == '__main__':
    suite = unittest.TestSuite()
    suite.addTest(ApiTestCase('test_status'))
    suite.addTest(ApiTestCase('test_get_txt_file'))
    suite.addTest(ApiTestCase('test_check_txt_file'))
    suite.addTest(ApiTestCase('test_clear_txt_file'))
    suite.addTest(ApiTestCase('test_restart_service'))


    runner = unittest.TextTestRunner()
    runner.run(suite)
    #runner.run(suite2)

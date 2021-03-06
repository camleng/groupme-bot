import unittest
from unittest.mock import MagicMock
import cmbot
from datetime import datetime as dt
import json
from main import Main


class MainTest(unittest.TestCase):
    def setUp(self):
        args = get_arguments()
        self.main = Main(args)
    
    def test_post_when_student_leader_meeting_is_today(self):
        self.main.bot.slack_url = slack_url
        self.main.specified_student_leader = MagicMock(return_value=True)
        self.main.bot.find_location = MagicMock(return_value=self.sl_location)
        self.main.bot.db.mark_as_sent = MagicMock()

        self.main.main()
        cmbot.requests.post.assert_any_call('https://api.groupme.com/v3/bots/post', data=self.get_groupme_payload(self.sl_message))
        cmbot.requests.post.assert_any_call(slack_url, data=self.get_slack_payload(self.sl_message))
    
    def test_post_when_conversations_meeting_is_today(self):
        cmbot.requests.post = MagicMock()
        self.main.bot.slack_url = slack_url
        self.main.specified_conversations = MagicMock(return_value=True)
        self.main.bot.find_location = MagicMock(return_value=self.c_location)
        self.main.bot.db.mark_as_sent = MagicMock()

        self.main.main()
        cmbot.requests.post.assert_any_call('https://api.groupme.com/v3/bots/post', data=self.get_groupme_payload(self.c_message))
        cmbot.requests.post.assert_any_call(slack_url, data=self.get_slack_payload(self.c_message))

    def test_error_when_not_specifying_meeting_type(self):
        code = self.main.main()
        assert code == 1
    
    def get_slack_payload(self, message):
        return {'payload': json.dumps({'text': message})}

    def get_groupme_payload(self, message):
        return {'bot_id': self.main.bot.id, 'text': message}

    @property
    def sl_message(self):
        return "Today's Student Leader meeting will be held in {building} {room}.".format_map(self.sl_location)

    @property
    def sl_location(self):
        return {
            'building': 'Walb',
            'room': '226',
            'date': {
                'month': 'Aug',
                'day': 21,
                'year': 2017
            },
            'sent': True
        }
    
    @property
    def c_message(self):
        return "Today's Conversations meeting will be held downstairs in the {building} {room}.".format_map(self.c_location)

    @property
    def c_location(self):
        return {
            'building': 'Walb',
            'room': 'Classic Ballroom',
            'date': {
                'month': 'Aug',
                'day': 23,
                'year': 2017
            },
            'sent': False
        }

def get_arguments():
    return {
        'student_leader': False,
        'conversations': False,
        'last_location': False,
        'dry_run': False,
        'clear_sent': False,
        'setup': False
    }

@property
def slack_url():
    return 'https://hooks.slack.com/services/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'

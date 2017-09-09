from datetime import datetime, timedelta
import urllib3
import base64
import os
import re
import json
import sys
import pickle

import certifi
import requests

from database import Database
from gmail import Gmail


class CMBot:
    def __init__(self, setup=False):
        self.db = Database(setup)
        self.id = self.db.get_bot_id()
        self.slack_url = self.db.slack_url
        self.gmail = Gmail()

    def post(self, message: str):
        # Uses SSL certification verification through certifi
        requests.post('https://api.groupme.com/v3/bots/post', data=self.get_payload('GroupMe', message))
        if self.slack_url:
            requests.post(self.slack_url, data=self.get_payload('Slack', message))

    def get_payload(self, service, message):
        if service == 'GroupMe':
            payload = {'bot_id': self.id, 'text': message}
        elif service == 'Slack':
            payload = {'payload': json.dumps({'text': message})}
        return payload

    def last_location(self, meeting_type, sentence=False):
        location = self.db.last_location(meeting_type)
        if 'date' in location:
            location['date'] = datetime.strptime('{month} {day}, {year}'.format_map(location['date']), '%b %d, %Y')
            return self.build_sentence(location) if sentence else location

    def build_sentence(self, location):
        if {'building', 'room'} <= set(location):
            return 'The {date.month}/{date.day} meeting was held in {building} {room}'.format_map(location)
        return 'There was no meeting on {date.month}/{date.day}'.format_map(location)

    def update_location(self, location, meeting_type):
        location['date'] = self.date_to_dict(location['date'])
        self.db.update_location(location, meeting_type)
    
    def check_for_early_exit(self, meeting_type):
        try:
            self.check_message_sent_today(meeting_type)
            self.check_no_student_leader_meeting_today(meeting_type)
            self.check_no_conversations_meeting_today(meeting_type)
        except Exception as e:
            print(e)
            location = self.last_location(meeting_type, sentence=True)
            if location:
                print(location)
            exit(1)

    def check_message_sent_today(self, meeting_type):
        if self.db.message_sent_today(meeting_type):
            raise Exception('Message already sent') 

    def check_no_student_leader_meeting_today(self, meeting_type):
        if meeting_type == 'student_leader' and self.is_not_day('Monday'):
            raise Exception('No Student Leader meeting scheduled today')
    
    def is_not_day(self, day: str):
        return datetime.today().strftime('%A') != day

    def check_no_conversations_meeting_today(self, meeting_type):
        if meeting_type == 'conversations' and self.is_not_day('Wednesday'):
            raise Exception('No Conversations meeting scheduled today')

    def find_location(self, meeting_type):
        self.check_for_early_exit(meeting_type)
        service = self.gmail.authorize()
        email_id = self.gmail.get_last_email_id(service)
        message, headers = self.gmail.get_email_info(service, email_id)
        return self.find_meeting_location(meeting_type, message, headers)

    def find_meeting_location(self, meeting_type, message, headers):
        if meeting_type == 'student_leader':
            return self.find_student_leader_meeting(message, headers)
        elif meeting_type == 'conversations':
            return self.find_conversations_meeting(message, headers)

    def correct_date(self, email_date, weekday):
        # if the email isn't sent on Monday
        while email_date.weekday() != weekday:
            email_date += timedelta(days=1)
        return email_date

    def date_to_dict(self, date):
        return dict(zip(['month', 'day', 'year'], date.strftime('%b %d %Y').split()))

    def find_student_leader_meeting(self, message, headers):
        building, room = self.extract_student_leader_room(message)
        email_date = self.find_date(headers, weekday=0)

        if datetime.today().date() == email_date.date():
            location = {'building': building, 'room': room, 'date': self.date_to_dict(email_date), 'sent': False}
            self.db.update_location(location, 'student_leader')
            return location
       
        raise Exception('No Student Leader meeting scheduled today')

    def extract_student_leader_room(self, message):
        """Finds the building and room number of the meeting
        """
        pattern = re.compile("""
        student
        \s*
        leader
        s?                             # optional plural
        \s*
        meeting:
        \s*
        monday,                        # day of the week
        \s*
        \w+                            # month
        \s*
        \d\d?                          # day, optionally 1 digit
        \w+                            # day ending ('st', 'th')
        ,?                             # optional comma
        \s*
        (?:\w+|\d+)                    # starting time (noon or 12)
        \s*
        -
        \s*
        1(?::00)?                      # ending time (1 or 1:00)
        \s*
        p\.?m\.?,                      # 'pm' or 'p.m.'
        \s*
        (liberal\s*arts|l\.a\.|walb)   # building
        \s*
        \w*                            # extra info such as 'union' after 'walb'
        \s*
        \w*,
        \s*
        room
        \s*
        (
        [g-]*                          # optional ground floor and hyphen ('G08', 'G-21')
        \d{2}\d?                       # room number, max of 3 digits
        )
        """, re.X)
        match = re.search(pattern, message)

        if match and len(match.groups()) == 2:
            return self.correct_student_leader_room(*match.groups())
        raise Exception('No meeting location found in email')

    def correct_building_name(self, building: str, room: str):
        return ('LA' if building in ['liberal arts', 'l.a.'] else building.capitalize()), room.capitalize()

    def zero_pad(str, day: str):
        if len(day) == 1:
            day = '0' + day
        return day

    def find_date(self, headers, weekday):
        """Uses the Gmail API to extract the header from the message
        and parse it for the date the email was sent.
        """
        for header in headers:
            if header['name'] == 'Date':
                day, month, year = header['value'].split()[1:4]
                day = self.zero_pad(day)
                date = datetime.strptime(f'{month} {day}, {year}', '%b %d, %Y')
                return self.correct_date(date, weekday)

    def dict_to_date(self, date: datetime) -> dict:
        return datetime.strptime('{month} {day}, {year}'.format_map(date), '%b %d, %Y')

    def pizza_night(self, date: dict):
        weekday, day = [int(t) for t in self.dict_to_date(date).strftime('%w %d').split()]
        return weekday == 3 and day - 7 <= 0

    def find_conversations_meeting(self, message, headers):    
        building, room = self.extract_conversations_room(message)
        email_date = self.find_date(headers, weekday=2)

        if datetime.today().date() == email_date.date():
            location = {'building': building, 'room': room, 'date': self.date_to_dict(email_date), 'sent': False}
            self.db.update_location(location, 'conversations')
            return location

        raise Exception('No Conversations meeting scheduled today')

    def extract_conversations_room(self, message):
        """Finds the building and room number of the meeting
        """
        # remove unnecessary formatting
        message = message.replace('=\r\n', '').replace('\r\n>', '')\
                .replace('=22', '"').replace('=46', 'F').lower()

        pattern = re.compile("""
        cm
        \s*
        "conversations"
        \s*
        meeting:
        \s*
        wednesday         # day of the week
        ,?
        \s*
        \w+               # month
        \s*
        \d\d?             # day, optionally 1 digit
        \w+?              # optional day ending ('st', 'nd', 'th')
        ,?
        \s*
        7(?::00)?         # starting time (7 or 7:30)
        \s*
        -
        \s*
        8:30              # ending time
        \s*
        p\.?m\.?,?          # 'pm' or 'p.m.'
        \s*
        (?:ipfw's\s*)?    # "IPFW's" Walb Class Ballroom
        (walb)            # building (always Walb)
        ,?
        .*?
        (222|ballroom)""", re.X)
        match = pattern.search(message)

        if match and len(match.groups()) == 2:
            return self.correct_conversations_room(*match.groups())
        raise Exception('No meeting location found in email')

    def correct_conversations_room(self, building, room):
        if room == 'ballroom':
            room = 'Classic Ballroom'
        elif room == '222':
            room = '222-226'
        return building.capitalize(), room

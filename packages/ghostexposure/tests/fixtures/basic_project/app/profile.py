"""Fixture: personal-data shaped fields (data pattern fires)."""


class Profile:
    def __init__(self, email, ssn, date_of_birth):
        self.email = email
        self.ssn = ssn
        self.date_of_birth = date_of_birth

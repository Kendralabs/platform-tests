#
# Copyright (c) 2015-2016 Intel Corporation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

import pytest

from modules.constants import TapComponent as TAP, Urls
from modules.runner.tap_test_case import TapTestCase
from modules.markers import components, priority
from modules.tap_object_model import LatestEvent, Organization, Transfer, User
from tests.fixtures import test_data


logged_components = (TAP.latest_events_service,)
pytestmark = [components.latest_events_service]


class DashboardLatestEvents(TapTestCase):

    @pytest.fixture(scope="class", autouse=True)
    def produce_events_in_test_org(self, test_org, add_admin_to_test_org, class_context):
        self.step("Produce an event in the tested organization - create a data set")
        transfer = Transfer.api_create(class_context, org_guid=test_org.guid, source=Urls.test_transfer_link)
        transfer.ensure_finished()
        self.step("Create another organization and create a data set in that organization")
        other_org = Organization.api_create(class_context)
        self.step("Add admin to the second organization")
        User.get_admin().api_add_to_organization(org_guid=other_org.guid)
        transfer = Transfer.api_create(class_context, org_guid=other_org.guid, source=Urls.test_transfer_link)
        transfer.ensure_finished()

    @priority.high
    def test_10_latest_events_on_dashboard_the_same_as_in_LES(self):
        self.step("Retrieve latest events from dashboard")
        self.dashboard_latest_events = LatestEvent.api_get_latest_events_from_org_metrics(test_data.TestData.test_org.guid)
        self.step("Retrieve latest events from the LES, filtering with tested organization")
        latest_events_response = LatestEvent.api_get_latest_events(org_guid=test_data.TestData.test_org.guid)
        self.step("Check that dashboard contains 10 latest events from LES")
        ten_latest_events = sorted(latest_events_response, reverse=True)[:10]
        self.assertUnorderedListEqual(ten_latest_events, self.dashboard_latest_events)
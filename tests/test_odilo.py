# encoding: utf-8
import json

from nose.tools import (
    eq_, 
    ok_, 
    assert_raises,
    set_trace,
)

from api.authenticator import BasicAuthenticationProvider
from api.odilo import (
    OdiloAPI,
    MockOdiloAPI,
    RecentOdiloCollectionMonitor,
    FullOdiloCollectionMonitor
)

from api.circulation import (
    CirculationAPI,
)

from api.circulation_exceptions import *

from . import (
    DatabaseTest,
    sample_data
)

from core.model import (
    DataSource,
    ExternalIntegration,
    Identifier,
    Representation,
    DeliveryMechanism
)


class OdiloAPITest(DatabaseTest):
    PIN = 'c4ca4238a0b923820dcc509a6f75849b'
    RECORD_ID = '00010982'

    def setup(self):
        super(OdiloAPITest, self).setup()
        library = self._default_library
        self.patron = self._patron()
        self.patron.authorization_identifier='0001000265'
        self.collection = MockOdiloAPI.mock_collection(self._db)
        self.circulation = CirculationAPI(
            self._db, library, api_map={ExternalIntegration.ODILO: MockOdiloAPI}
        )
        self.api = self.circulation.api_for_collection[self.collection.id]

        self.edition, self.licensepool = self._edition(
            data_source_name=DataSource.ODILO,
            identifier_type=Identifier.ODILO_ID,
            collection=self.collection,
            identifier_id=self.RECORD_ID,
            with_license_pool=True
        )

    @classmethod
    def sample_data(cls, filename):
        return sample_data(filename, 'odilo')

    @classmethod
    def sample_json(cls, filename):
        data = cls.sample_data(filename)
        return data, json.loads(data)

    def error_message(self, error_code, message=None, token=None):
        """Create a JSON document that simulates the message served by
        Odilo given a certain error condition.
        """
        message = message or self._str
        token = token or self._str
        data = dict(errorCode=error_code, message=message, token=token)
        return json.dumps(data)


class TestOdiloAPI(OdiloAPITest):

    def test_run_self_tests(self):
        """Verify that OdiloAPI.run_self_tests() calls the right
        methods.
        """
        class Mock(MockOdiloAPI):
            "Mock every method used by OdiloAPI.run_self_tests."

            def __init__(self, _db, collection):
                """Stop the default constructor from running."""
                self._db = _db
                self.collection_id = collection.id

            # First we will call check_creds() to get a fresh credential.
            mock_credential = object()
            def check_creds(self, force_refresh=False):
                self.check_creds_called_with = force_refresh
                return self.mock_credential

            # Finally, for every library associated with this
            # collection, we'll call get_patron_credential() using
            # the credentials of that library's test patron.
            mock_patron_credential = object()
            get_patron_access_token_called_with = []
            def get_patron_access_token(self, credential, patron, pin):
                self.get_patron_access_token_called_with.append(
                    (credential, patron, pin)
                )
                return self.mock_patron_credential

        # Now let's make sure two Libraries have access to this
        # Collection -- one library with a default patron and one
        # without.
        no_default_patron = self._library(name="no patron")
        self.collection.libraries.append(no_default_patron)

        with_default_patron = self._default_library
        integration = self._external_integration(
            "api.simple_authentication",
            ExternalIntegration.PATRON_AUTH_GOAL,
            libraries=[with_default_patron]
        )
        p = BasicAuthenticationProvider
        integration.setting(p.TEST_IDENTIFIER).value = "username1"
        integration.setting(p.TEST_PASSWORD).value = "password1"

        # Now that everything is set up, run the self-test.
        api = Mock(self._db, self.collection)
        results = sorted(
            api.run_self_tests(self._db), key=lambda x: x.name
        )
        token_failure, token_success, sitewide = results

        # Make sure all three tests were run and got the expected result.
        #

        # We got a sitewide access token.
        eq_('Obtaining a sitewide access token', sitewide.name)
        eq_(True, sitewide.success)
        eq_(api.mock_credential, sitewide.result)
        eq_(True, api.check_creds_called_with)

        # We got a patron access token for the library that had
        # a default patron configured.
        eq_(
            'Obtaining a patron access token for the test patron for library %s' % with_default_patron.name,
            token_success.name
        )
        eq_(True, token_success.success)
        # get_patron_access_token was only called once.
        [(credential, patron, pin)] = api.get_patron_access_token_called_with
        eq_(patron, credential.patron)
        eq_("username1", patron.authorization_identifier)
        eq_("password1", pin)
        eq_(api.mock_patron_credential, token_success.result)

        # We couldn't get a patron access token for the other library.
        eq_(
            'Acquiring test patron credentials for library %s' % no_default_patron.name,
            token_failure.name
        )
        eq_(False, token_failure.success)
        eq_("Library has no test patron configured.",
            token_failure.exception.message)

    def test_run_self_tests_short_circuit(self):
        """If OdiloAPI.check_creds can't get credentials, the rest of
        the self-tests aren't even run.
        """

        # NOTE: this isn't as foolproof as it seems. If there's a
        # problem getting the credentials, that problem will most
        # likely happen during the OdiloAPI constructor, and
        # we won't even get a chance to run the tests.
        def explode(*args, **kwargs):
            raise Exception("Failure!")
        self.api.check_creds = explode

        # Only one test will be run.
        [check_creds] = self.api.run_self_tests(self._db)
        eq_("Failure!", check_creds.exception.message)


class TestOdiloCirculationAPI(OdiloAPITest):
    #################
    # General tests
    #################

    # Test 404 Not Found --> patron not found --> 'patronNotFound'
    def test_01_patron_not_found(self):
        patron_not_found_data, patron_not_found_json = self.sample_json("error_patron_not_found.json")
        self.api.queue_response(404, content=patron_not_found_json)

        patron = self._patron()
        patron.authorization_identifier = "no such patron"
        assert_raises(PatronNotFoundOnRemote, self.api.checkout, patron, self.PIN, self.licensepool, 'ACSM_EPUB')
        self.api.log.info('Test patron not found ok!')

    # Test 404 Not Found --> record not found --> 'ERROR_DATA_NOT_FOUND'
    def test_02_data_not_found(self):
        data_not_found_data, data_not_found_json = self.sample_json("error_data_not_found.json")
        self.api.queue_response(404, content=data_not_found_json)

        self.licensepool.identifier.identifier = '12345678'
        assert_raises(NotFoundOnRemote, self.api.checkout, self.patron, self.PIN, self.licensepool, 'ACSM_EPUB')
        self.api.log.info('Test resource not found on remote ok!')

    def test_make_absolute_url(self):

        # A relative URL is made absolute using the API's base URL.
        relative = "/relative-url"
        absolute = self.api._make_absolute_url(relative)
        eq_(absolute, self.api.library_api_base_url + relative)

        # An absolute URL is not modified.
        for protocol in ('http', 'https'):
            already_absolute = "%s://example.com/" % protocol 
            eq_(already_absolute, self.api._make_absolute_url(already_absolute))


    #################
    # Checkout tests
    #################

    # Test 400 Bad Request --> Invalid format for that resource
    def test_11_checkout_fake_format(self):
        self.api.queue_response(400, content="")
        assert_raises(NoAcceptableFormat, self.api.checkout, self.patron, self.PIN, self.licensepool, 'FAKE_FORMAT')
        self.api.log.info('Test invalid format for resource ok!')

    def test_12_checkout_acsm_epub(self):
        checkout_data, checkout_json = self.sample_json("checkout_acsm_epub_ok.json")
        self.api.queue_response(200, content=checkout_json)
        self.perform_and_validate_checkout('ACSM_EPUB')

    def test_13_checkout_acsm_pdf(self):
        checkout_data, checkout_json = self.sample_json("checkout_acsm_pdf_ok.json")
        self.api.queue_response(200, content=checkout_json)
        self.perform_and_validate_checkout('ACSM_PDF')

    def test_14_checkout_ebook_streaming(self):
        checkout_data, checkout_json = self.sample_json("checkout_ebook_streaming_ok.json")
        self.api.queue_response(200, content=checkout_json)
        self.perform_and_validate_checkout('EBOOK_STREAMING')

    def test_mechanism_set_on_borrow(self):
        """The delivery mechanism for an Odilo title is set on checkout."""
        eq_(OdiloAPI.SET_DELIVERY_MECHANISM_AT, OdiloAPI.BORROW_STEP)

    def perform_and_validate_checkout(self, internal_format):
        loan_info = self.api.checkout(self.patron, self.PIN, self.licensepool, internal_format)
        ok_(loan_info, msg="LoanInfo null --> checkout failed!")
        self.api.log.info('Loan ok: %s' % loan_info.identifier)

    #################
    # Fulfill tests
    #################

    def test_21_fulfill_acsm_epub(self):
        checkout_data, checkout_json = self.sample_json("patron_checkouts.json")
        self.api.queue_response(200, content=checkout_json)

        acsm_data = self.sample_data("fulfill_ok_acsm_epub.acsm")
        self.api.queue_response(200, content=acsm_data)

        fulfillment_info = self.fulfill('ACSM_EPUB')
        eq_(fulfillment_info.content_type[0], Representation.EPUB_MEDIA_TYPE)
        eq_(fulfillment_info.content_type[1], DeliveryMechanism.ADOBE_DRM)

    def test_22_fulfill_acsm_pdf(self):
        checkout_data, checkout_json = self.sample_json("patron_checkouts.json")
        self.api.queue_response(200, content=checkout_json)

        acsm_data = self.sample_data("fulfill_ok_acsm_pdf.acsm")
        self.api.queue_response(200, content=acsm_data)

        fulfillment_info = self.fulfill('ACSM_PDF')
        eq_(fulfillment_info.content_type[0], Representation.PDF_MEDIA_TYPE)
        eq_(fulfillment_info.content_type[1], DeliveryMechanism.ADOBE_DRM)

    def test_23_fulfill_ebook_streaming(self):
        checkout_data, checkout_json = self.sample_json("patron_checkouts.json")
        self.api.queue_response(200, content=checkout_json)

        self.licensepool.identifier.identifier = '00011055'
        fulfillment_info = self.fulfill('EBOOK_STREAMING')
        eq_(fulfillment_info.content_type[0], Representation.TEXT_HTML_MEDIA_TYPE)
        eq_(fulfillment_info.content_type[1], DeliveryMechanism.STREAMING_TEXT_CONTENT_TYPE)

    def fulfill(self, internal_format):
        fulfillment_info = self.api.fulfill(self.patron, self.PIN, self.licensepool, internal_format)
        ok_(fulfillment_info, msg='Cannot Fulfill !!')

        if fulfillment_info.content_link:
            self.api.log.info('Fulfill link: %s' % fulfillment_info.content_link)
        if fulfillment_info.content:
            self.api.log.info('Fulfill content: %s' % fulfillment_info.content)

        return fulfillment_info

    #################
    # Hold tests
    #################

    def test_31_already_on_hold(self):
        already_on_hold_data, already_on_hold_json = self.sample_json("error_hold_already_in_hold.json")
        self.api.queue_response(403, content=already_on_hold_json)

        assert_raises(AlreadyOnHold, self.api.place_hold, self.patron, self.PIN, self.licensepool,
                      'ejcepas@odilotid.es')

        self.api.log.info('Test hold already on hold ok!')

    def test_32_place_hold(self):
        hold_ok_data, hold_ok_json = self.sample_json("place_hold_ok.json")
        self.api.queue_response(200, content=hold_ok_json)

        hold_info = self.api.place_hold(self.patron, self.PIN, self.licensepool, 'ejcepas@odilotid.es')
        ok_(hold_info, msg="HoldInfo null --> place hold failed!")
        self.api.log.info('Hold ok: %s' % hold_info.identifier)

    #################
    # Patron Activity tests
    #################

    def test_41_patron_activity_invalid_patron(self):
        patron_not_found_data, patron_not_found_json = self.sample_json("error_patron_not_found.json")
        self.api.queue_response(404, content=patron_not_found_json)

        assert_raises(PatronNotFoundOnRemote, self.api.patron_activity, self.patron, self.PIN)

        self.api.log.info('Test patron activity --> invalid patron ok!')

    def test_42_patron_activity(self):
        patron_checkouts_data, patron_checkouts_json = self.sample_json("patron_checkouts.json")
        patron_holds_data, patron_holds_json = self.sample_json("patron_holds.json")
        self.api.queue_response(200, content=patron_checkouts_json)
        self.api.queue_response(200, content=patron_holds_json)

        loans_and_holds = self.api.patron_activity(self.patron, self.PIN)
        ok_(loans_and_holds)
        eq_(12, len(loans_and_holds))
        self.api.log.info('Test patron activity ok !!')

    #################
    # Checkin tests
    #################

    def test_51_checkin_patron_not_found(self):
        patron_not_found_data, patron_not_found_json = self.sample_json("error_patron_not_found.json")
        self.api.queue_response(404, content=patron_not_found_json)

        assert_raises(PatronNotFoundOnRemote, self.api.checkin, self.patron, self.PIN, self.licensepool)

        self.api.log.info('Test checkin --> invalid patron ok!')

    def test_52_checkin_checkout_not_found(self):
        checkout_not_found_data, checkout_not_found_json = self.sample_json("error_checkout_not_found.json")
        self.api.queue_response(404, content=checkout_not_found_json)

        assert_raises(NotCheckedOut, self.api.checkin, self.patron, self.PIN, self.licensepool)

        self.api.log.info('Test checkin --> invalid checkout ok!')

    def test_53_checkin(self):
        checkout_data, checkout_json = self.sample_json("patron_checkouts.json")
        self.api.queue_response(200, content=checkout_json)

        checkin_data, checkin_json = self.sample_json("checkin_ok.json")
        self.api.queue_response(200, content=checkin_json)

        response = self.api.checkin(self.patron, self.PIN, self.licensepool)
        eq_(response.status_code, 200,
            msg="Response code != 200, cannot perform checkin for record: " + self.licensepool.identifier.identifier
                + " patron: " + self.patron.authorization_identifier)

        checkout_returned = response.json()

        ok_(checkout_returned)
        eq_('4318', checkout_returned['id'])
        self.api.log.info('Checkout returned: %s' % checkout_returned['id'])

    #################
    # Patron Activity tests
    #################

    def test_61_return_hold_patron_not_found(self):
        patron_not_found_data, patron_not_found_json = self.sample_json("error_patron_not_found.json")
        self.api.queue_response(404, content=patron_not_found_json)

        assert_raises(PatronNotFoundOnRemote, self.api.release_hold, self.patron, self.PIN, self.licensepool)

        self.api.log.info('Test release hold --> invalid patron ok!')

    def test_62_return_hold_not_found(self):
        holds_data, holds_json = self.sample_json("patron_holds.json")
        self.api.queue_response(200, content=holds_json)

        checkin_data, checkin_json = self.sample_json("error_hold_not_found.json")
        self.api.queue_response(404, content=checkin_json)

        response = self.api.release_hold(self.patron, self.PIN, self.licensepool)
        eq_(response, True,
            msg="Cannot release hold, response false " + self.licensepool.identifier.identifier + " patron: "
                + self.patron.authorization_identifier)

        self.api.log.info('Hold returned: %s' % self.licensepool.identifier.identifier)

    def test_63_return_hold(self):
        holds_data, holds_json = self.sample_json("patron_holds.json")
        self.api.queue_response(200, content=holds_json)

        release_hold_ok_data, release_hold_ok_json = self.sample_json("release_hold_ok.json")
        self.api.queue_response(200, content=release_hold_ok_json)

        response = self.api.release_hold(self.patron, self.PIN, self.licensepool)
        eq_(response, True,
            msg="Cannot release hold, response false " + self.licensepool.identifier.identifier + " patron: "
                + self.patron.authorization_identifier)

        self.api.log.info('Hold returned: %s' % self.licensepool.identifier.identifier)


class TestOdiloDiscoveryAPI(OdiloAPITest):
    def test_1_odilo_recent_circulation_monitor(self):
        monitor = RecentOdiloCollectionMonitor(self._db, self.collection, api_class=MockOdiloAPI)
        ok_(monitor, 'Monitor null !!')
        eq_(ExternalIntegration.ODILO, monitor.protocol, 'Wat??')

        records_metadata_data, records_metadata_json = self.sample_json("records_metadata.json")
        monitor.api.queue_response(200, content=records_metadata_data)

        availability_data = self.sample_data("record_availability.json")
        for record in records_metadata_json:
            monitor.api.queue_response(200, content=availability_data)

        monitor.api.queue_response(200, content='[]')  # No more resources retrieved

        monitor.run_once(start="2017-09-01", cutoff=None)

        self.api.log.info('RecentOdiloCollectionMonitor finished ok!!')

    def test_2_odilo_full_circulation_monitor(self):
        monitor = FullOdiloCollectionMonitor(self._db, self.collection, api_class=MockOdiloAPI)
        ok_(monitor, 'Monitor null !!')
        eq_(ExternalIntegration.ODILO, monitor.protocol, 'Wat??')

        records_metadata_data, records_metadata_json = self.sample_json("records_metadata.json")
        monitor.api.queue_response(200, content=records_metadata_data)

        availability_data = self.sample_data("record_availability.json")
        for record in records_metadata_json:
            monitor.api.queue_response(200, content=availability_data)

        monitor.api.queue_response(200, content='[]')  # No more resources retrieved

        monitor.run_once()

        self.api.log.info('FullOdiloCollectionMonitor finished ok!!')

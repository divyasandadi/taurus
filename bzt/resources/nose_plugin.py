from time import time

from nose.plugins import Plugin
from nose import run
import traceback
import sys
import csv
import re

try:
    from lxml import etree
except ImportError:
    try:
        import cElementTree as etree
    except ImportError:
        import elementtree.ElementTree as etree

JTL_ERR_ATRS = ["t", "lt", "ct", "ts", "s", "lb", "rc", "rm", "tn", "dt", "de", "by", "ng", "na"]

JTL_HEADER = ["timeStamp", "elapsed", "label", "responseCode", "responseMessage", "threadName", "success",
              "grpThreads", "allThreads", "Latency", "Connect"]

SEARCH_PATTERNS = {"file": re.compile(r'\((.*?)\.'), "class": re.compile(r'\.(.*?)\)'),
                   "method": re.compile(r'(.*?)\ ')}


class TaurusNosePlugin(Plugin):
    """
    Output test results in a format suitable for Taurus report.
    """

    name = 'nose_plugin'
    enabled = True

    def __init__(self, output_file, err_file):
        super(TaurusNosePlugin, self).__init__()
        self._module_name = None
        self._method_name = None
        self.output_file = output_file
        self.err_file = err_file
        self.test_count = 0
        self.success = 0
        self.csv_writer = None
        self.jtl_dict = None
        self.error_writer = None
        self.last_err = None

    def addError(self, test, err, capt=None):
        """
        when a test raises an uncaught exception
        :param test:
        :param err:
        :return:
        """
        self.jtl_dict["responseCode"] = "500"
        self.last_err = err

    def addFailure(self, test, err, capt=None, tbinfo=None):
        """
        when a test fails
        :param test:
        :param err:

        :return:
        """
        self.jtl_dict["responseCode"] = "404"
        self.last_err = err

    def addSkip(self, test):
        """
        when a test is skipped
        :param test:
        :return:
        """
        self.jtl_dict["responseCode"] = "300"

    def addSuccess(self, test, capt=None):
        """
        when a test passes
        :param test:
        :return:
        """
        self.jtl_dict["responseCode"] = "200"
        self.jtl_dict["success"] = "true"
        self.jtl_dict["responseMessage"] = "OK"
        self.success += 1

    def begin(self):
        """
        Before any test runs
        open descriptor here
        :return:
        """
        self.out_stream = open(self.output_file, "wt")
        self.csv_writer = csv.DictWriter(self.out_stream, delimiter=',', fieldnames=JTL_HEADER)

        self.err_stream = open(self.err_file, "wb")
        self.error_writer = JTLErrorWriter(self.err_stream)

        self.csv_writer.writeheader()
        self._module_name = ""

    def finalize(self, result):
        """
        After all tests
        :param result:
        :return:
        """
        self.error_writer.close()
        self.out_stream.close()
        self.err_stream.close()
        if not self.test_count:
            raise RuntimeError("Nothing to test.")

    def startTest(self, test):
        """
        before test run
        :param test:
        :return:
        """
        full_test_name = str(test)

        file_name = SEARCH_PATTERNS["file"].findall(full_test_name)
        file_name = file_name[0] if file_name else ""

        class_name = SEARCH_PATTERNS["class"].findall(full_test_name)
        class_name = class_name[0] if class_name else ""

        method_name = SEARCH_PATTERNS["method"].findall(full_test_name)
        method_name = method_name[0] if method_name else ""

        if self._module_name != file_name + "." + class_name:
            self._module_name = file_name + "." + class_name

        self._method_name = method_name
        self.last_err = None
        self._time = time()
        self.jtl_dict = {}.fromkeys(JTL_HEADER, 0)
        self.jtl_dict["timeStamp"] = int(1000 * self._time)
        self.jtl_dict["label"] = self._method_name
        self.jtl_dict["threadName"] = self._module_name
        self.jtl_dict["grpThreads"] = 1
        self.jtl_dict["allThreads"] = 1
        self.jtl_dict["success"] = "false"

    def stopTest(self, test):
        """
        after the test has been run
        :param test:
        :return:
        """
        self.test_count += 1
        self.jtl_dict["elapsed"] = str(int(1000 * (time() - self._time)))

        if self.last_err is not None:
            exc_type_name = self.last_err[0].__name__
            trace = "".join(traceback.format_tb(self.last_err[2])) + "\n" + self.last_err[1]
            self.jtl_dict["responseMessage"] = exc_type_name

            sample = {}.fromkeys(JTL_ERR_ATRS)
            sample["t"] = self.jtl_dict["elapsed"]
            sample["lt"] = str(self.jtl_dict["Latency"])
            sample["ct"] = str(self.jtl_dict["Connect"])
            sample["ts"] = str(self.jtl_dict["timeStamp"])
            sample["s"] = self.jtl_dict["success"]
            sample["lb"] = self.jtl_dict["label"]
            sample["rc"] = self.jtl_dict["responseCode"]
            sample["rm"] = exc_type_name
            sample["tn"] = self.jtl_dict["threadName"]
            sample["dt"] = "text"
            sample["de"] = ""
            sample["by"] = str(len(trace))
            sample["ng"] = "1"
            sample["na"] = "1"

            self.error_writer.add_sample(sample, self.jtl_dict["label"], trace)

        self.csv_writer.writerow(self.jtl_dict)

        report_pattern = "%s.%s,Total:%d Pass:%d Failed:%d\n"
        sys.stdout.write(report_pattern % (
            self._module_name, self._method_name, self.test_count, self.success, self.test_count - self.success))

        self.out_stream.flush()


class JTLErrorWriter(object):
    def __init__(self, fds):
        self.out_file_fds = fds
        self.xml_writer = write_element(self.out_file_fds)
        next(self.xml_writer)

    def add_sample(self, sample, url, resp_data):
        new_sample = self.gen_httpSample(sample, url, resp_data)
        self.xml_writer.send(new_sample)

    def gen_httpSample(self, sample, url, resp_data):
        """
        :param params: namedtuple httpSample
        :return:
        """
        sample_element = etree.Element("httpSample", **sample)
        sample_element.append(self.gen_resp_header())
        sample_element.append(self.gen_req_header())
        sample_element.append(self.gen_resp_data(resp_data))
        sample_element.append(self.gen_cookies())
        sample_element.append(self.gen_method())
        sample_element.append(self.gen_queryString())
        sample_element.append(self.gen_url(url))
        return sample_element

    def gen_resp_header(self):
        resp_header = etree.Element("responseHeader")
        resp_header.set("class", "java.lang.String")
        return resp_header

    def gen_req_header(self):
        resp_header = etree.Element("requestHeader")
        resp_header.set("class", "java.lang.String")
        return resp_header

    def gen_resp_data(self, data):
        resp_data = etree.Element("responseData")
        resp_data.set("class", "java.lang.String")
        resp_data.text = data
        return resp_data

    def gen_cookies(self):
        cookies = etree.Element("cookies")
        cookies.set("class", "java.lang.String")
        return cookies

    def gen_method(self):
        method = etree.Element("method")
        method.set("class", "java.lang.String")
        return method

    def gen_queryString(self):
        queryString = etree.Element("queryString")
        queryString.set("class", "java.lang.String")
        return queryString

    def gen_url(self, url):
        url_element = etree.Element("java.net.URL")
        url_element.text = url
        return url_element

    def close(self):
        self.xml_writer.close()

def write_element(fds):
    with etree.xmlfile(fds, buffered=False, encoding="UTF-8") as xf:
        xf.write_declaration()
        with xf.element('testResults', version="1.2"):
            try:
                while True:
                    el = (yield)
                    xf.write(el)
                    xf.flush()
            except GeneratorExit:
                pass


if __name__ == "__main__":
    _output_file = sys.argv[1]
    _err_file = sys.argv[2]
    test_path = sys.argv[3:]
    argv = [__file__, '-v']
    argv.extend(test_path)
    run(addplugins=[TaurusNosePlugin(_output_file, _err_file)], argv=argv + ['--with-nose_plugin'] + ['--nocapture'])
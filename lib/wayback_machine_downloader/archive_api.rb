require 'json'
require 'uri'

module ArchiveAPI

  def get_raw_list_from_api url, page_index, http
    request_url = URI("https://web.archive.org/cdx/search/xd")
    params = [["output", "json"], ["url", url]]
    params += parameters_for_api page_index
    request_url.query = URI.encode_www_form(params)

    begin
      response = http.get(request_url.request_uri)
      return nil unless response.is_a?(Net::HTTPSuccess)
      json = JSON.parse(response.body)
      return nil unless json.is_a?(Array)
      json.shift if json[0] == ["timestamp", "original"]
      json
    rescue JSON::ParserError, IOError, EOFError, Timeout::Error,
           OpenSSL::SSL::SSLError, SocketError, SystemCallError
      nil
    end
  end

  # nil means the request failed. An empty array is a real empty page.
  def fetch_snapshot_page url, page_index, http
    3.times do |attempt|
      list = get_raw_list_from_api(url, page_index, http)
      return list unless list.nil?
      sleep(1 + attempt)
    end
    []
  end

  def num_snapshot_pages url, http
    request_url = URI("https://web.archive.org/cdx/search/xd")
    params = [["url", url], ["showNumPages", "true"]]
    params += parameters_for_api(nil).reject { |key, _value| key == "fl" }
    request_url.query = URI.encode_www_form(params)
    response = http.get(request_url.request_uri)
    return nil unless response.is_a?(Net::HTTPSuccess)
    Integer(response.body.strip)
  rescue ArgumentError, IOError, EOFError, Timeout::Error,
         OpenSSL::SSL::SSLError, SocketError, SystemCallError
    nil
  end

  def parameters_for_api page_index
    parameters = [["fl", "timestamp,original"], ["collapse", "digest"], ["gzip", "false"]]
    if !@all
      parameters.push(["filter", "statuscode:200"])
    end
    if @from_timestamp and @from_timestamp != 0
      parameters.push(["from", @from_timestamp.to_s])
    end
    if @to_timestamp and @to_timestamp != 0
      parameters.push(["to", @to_timestamp.to_s])
    end
    if page_index
      parameters.push(["page", page_index])
    end
    parameters
  end

end

admin = """
<!doctype html>
<html>
<head>
<title>Circulation Manager</title>
<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
</head>
<body>
  <script src=\"/admin/static/circulation-web.js\"></script>
  <script>
    var circulationWeb = new CirculationWeb({
        csrfToken: \"{{ csrf_token }}\",
        homeUrl: \"{{ home_url }}\",
        showCircEventsDownload: {{ "true" if show_circ_events_download else "false" }}
    });
  </script>
</body>
</html>
"""

admin_sign_in_again = """
<!doctype html>
<html>
<head><title>Circulation Manager</title></head>
<body>
  <p>You are now logged in. You may close this window and try your request again.
</body>
</html>
"""

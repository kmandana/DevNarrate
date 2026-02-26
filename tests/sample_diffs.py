"""Reusable sample diffs for secret_scanner tests.

NOTE: Test tokens are constructed via concatenation to avoid triggering
GitHub push protection. These are fake/example values, not real secrets.
"""

# Build fake test tokens at runtime to avoid GitHub push protection.
# These are NOT real secrets — they're constructed patterns for testing
# that our scanner correctly detects each provider's key format.
_SK = "sk" + "_live_"  # Stripe prefix  # pragma: allowlist secret
_XO = "xo" + "xb-"  # Slack prefix  # pragma: allowlist secret

DIFF_WITH_AWS_KEY = """\
diff --git a/config.py b/config.py
new file mode 100644
--- /dev/null
+++ b/config.py
@@ -0,0 +1,3 @@
+import os
+
+AWS_ACCESS_KEY_ID = "AKIAIOSFODNN7EXAMPLE"
"""

DIFF_WITH_MULTIPLE_SECRETS = (
    "diff --git a/config.py b/config.py\n"
    "new file mode 100644\n"
    "--- /dev/null\n"
    "+++ b/config.py\n"
    "@@ -0,0 +1,6 @@\n"
    '+AWS_KEY = "AKIAIOSFODNN7EXAMPLE"\n'
    '+DB_PASSWORD = "admin123"\n'
    '+GITHUB_TOKEN = "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefgh"\n'
    '+SECRET = "my_super_secret_value"\n'
    f'+STRIPE_KEY = "{_SK}abc123def456ghi789jklmno"\n'
    f'+SLACK_TOKEN = "{_XO}1234567890-abcdefghijklmn"\n'
)

DIFF_CLEAN = """\
diff --git a/app.py b/app.py
new file mode 100644
--- /dev/null
+++ b/app.py
@@ -0,0 +1,5 @@
+import os
+
+def hello():
+    print("Hello, World!")
+    return True
"""

DIFF_WITH_SUPPRESSED_SECRET = """\
diff --git a/config.py b/config.py
new file mode 100644
--- /dev/null
+++ b/config.py
@@ -0,0 +1,3 @@
+# This key is for testing only
+AWS_KEY = "AKIAIOSFODNN7EXAMPLE"  # pragma: allowlist secret
+DEBUG = True
"""

DIFF_WITH_FALSE_POSITIVES = """\
diff --git a/app.py b/app.py
--- a/app.py
+++ b/app.py
@@ -1,3 +1,7 @@
 import os
+
+password = os.environ["DB_PASSWORD"]
+secret = get_secret_from_vault()
+token = "${API_TOKEN}"
+api_key = config.get("api_key")

"""

DIFF_WITH_SIMPLE_PASSWORD = """\
diff --git a/settings.py b/settings.py
new file mode 100644
--- /dev/null
+++ b/settings.py
@@ -0,0 +1,3 @@
+DATABASE_HOST = "localhost"
+DATABASE_PASSWORD = "changeme"
+DEBUG = True
"""

DIFF_MULTI_FILE = (
    "diff --git a/src/config.py b/src/config.py\n"
    "--- a/src/config.py\n"
    "+++ b/src/config.py\n"
    "@@ -5,3 +5,5 @@ import os\n"
    "\n"
    ' DATABASE_URL = os.environ["DATABASE_URL"]\n'
    f'+STRIPE_SECRET = "{_SK}51NKl3aBCD1234567890abcdef"\n'
    '+ADMIN_PASSWORD = "SuperSecret123!"\n'
    "\n"
    "diff --git a/src/app.py b/src/app.py\n"
    "--- a/src/app.py\n"
    "+++ b/src/app.py\n"
    "@@ -1,3 +1,5 @@\n"
    " from flask import Flask\n"
    "+import logging\n"
    "+\n"
    " app = Flask(__name__)\n"
    "\n"
)

DIFF_WITH_PRIVATE_KEY = """\
diff --git a/deploy/key.pem b/deploy/key.pem
new file mode 100644
--- /dev/null
+++ b/deploy/key.pem
@@ -0,0 +1,5 @@
+-----BEGIN RSA PRIVATE KEY-----
+MIIEpAIBAAKCAQEA0Z3VS5JJcds3xfn/yGaXxw2FtBv0s0gR
+AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
+MIIEpAIBAAKCAQEA0Z3VS5JJcds3xfn/yGaXxw2FtBv0s0gR
+-----END RSA PRIVATE KEY-----
"""

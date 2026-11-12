package com.iot.monitor

import android.annotation.SuppressLint
import android.app.Activity
import android.app.DownloadManager
import android.content.ContentValues
import android.content.Context
import android.content.SharedPreferences
import android.graphics.Color
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Environment
import android.provider.MediaStore
import android.text.InputType
import android.util.Base64
import android.util.Log
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.webkit.JavascriptInterface
import android.webkit.WebChromeClient
import android.webkit.WebResourceRequest
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Button
import android.widget.EditText
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.ProgressBar
import android.widget.TextView
import android.widget.Toast
import org.json.JSONObject
import java.io.File
import java.io.FileOutputStream
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder

class MainActivity : Activity() {

    private lateinit var webView: WebView
    private lateinit var loginView: LinearLayout
    private lateinit var userInput: EditText
    private lateinit var passInput: EditText
    private lateinit var loginButton: Button
    private lateinit var errorText: TextView
    private lateinit var progress: ProgressBar
    private lateinit var prefs: SharedPreferences

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        prefs = getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)

        webView = WebView(this)
        webView.layoutParams = ViewGroup.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT,
            ViewGroup.LayoutParams.MATCH_PARENT
        )
        webView.settings.apply {
            javaScriptEnabled = true
            domStorageEnabled = true
            databaseEnabled = true
            loadWithOverviewMode = true
            useWideViewPort = true
            mediaPlaybackRequiresUserGesture = false
            mixedContentMode = WebSettings.MIXED_CONTENT_NEVER_ALLOW
            cacheMode = WebSettings.LOAD_DEFAULT
        }

        webView.addJavascriptInterface(Bridge(), "AndroidBridge")

        webView.webViewClient = object : WebViewClient() {
            override fun shouldOverrideUrlLoading(
                view: WebView?,
                request: WebResourceRequest?
            ): Boolean {
                val url = request?.url ?: return false
                if (url.scheme == "http" || url.scheme == "https") {
                    Log.d(TAG, "In-app: $url")
                    return false
                }
                Log.d(TAG, "Blocked scheme: $url")
                return true
            }

            override fun onPageFinished(view: WebView?, url: String?) {
                super.onPageFinished(view, url)
                view?.evaluateJavascript(INTERCEPT_JS, null)
            }
        }

        webView.webChromeClient = WebChromeClient()

        webView.setDownloadListener { url, userAgent, contentDisposition, mimeType, _ ->
            try {
                val request = DownloadManager.Request(Uri.parse(url))
                request.addRequestHeader("User-Agent", userAgent)
                request.setNotificationVisibility(
                    DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED
                )
                val fileName = android.webkit.URLUtil.guessFileName(url, contentDisposition, mimeType)
                request.setDestinationInExternalPublicDir(
                    Environment.DIRECTORY_DOWNLOADS,
                    fileName
                )
                val dm = getSystemService(DOWNLOAD_SERVICE) as DownloadManager
                dm.enqueue(request)
                Toast.makeText(this, "Descargando $fileName ...", Toast.LENGTH_SHORT).show()
            } catch (e: Exception) {
                Toast.makeText(this, "No se pudo descargar: ${e.message}", Toast.LENGTH_LONG).show()
            }
        }

        loginView = buildLoginView()

        val container = FrameLayout(this)
        container.addView(
            webView,
            FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT,
                FrameLayout.LayoutParams.MATCH_PARENT
            )
        )
        container.addView(
            loginView,
            FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT,
                FrameLayout.LayoutParams.MATCH_PARENT
            )
        )
        setContentView(container)

        val savedToken = prefs.getString(KEY_TOKEN, null)
        if (savedToken.isNullOrBlank()) {
            showLogin()
        } else {
            loginView.visibility = View.GONE
            webView.visibility = View.VISIBLE
            checkTokenAsync(savedToken)
        }
    }

    private fun dp(value: Int): Int = (value * resources.displayMetrics.density).toInt()

    private fun buildLoginView(): LinearLayout {
        val root = LinearLayout(this)
        root.orientation = LinearLayout.VERTICAL
        root.gravity = Gravity.CENTER
        root.setPadding(dp(32), dp(32), dp(32), dp(32))
        root.setBackgroundColor(Color.parseColor("#F7F9FC"))

        val title = TextView(this).apply {
            text = "IoT Monitor"
            textSize = 26f
            setTextColor(Color.parseColor("#1F2937"))
            gravity = Gravity.CENTER
        }
        val subtitle = TextView(this).apply {
            text = "Inicia sesión para ver el dashboard"
            textSize = 14f
            setTextColor(Color.parseColor("#6B7280"))
            gravity = Gravity.CENTER
        }

        userInput = EditText(this).apply {
            hint = "Usuario"
            inputType = InputType.TYPE_CLASS_TEXT
            setSingleLine(true)
        }
        passInput = EditText(this).apply {
            hint = "Contraseña"
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_PASSWORD
            setSingleLine(true)
        }
        errorText = TextView(this).apply {
            setTextColor(Color.parseColor("#DC2626"))
            textSize = 13f
            visibility = View.GONE
        }
        progress = ProgressBar(this).apply {
            visibility = View.GONE
        }
        loginButton = Button(this).apply {
            text = "Ingresar"
            setOnClickListener { performLogin() }
        }
        val forgotButton = Button(this).apply {
            text = "Recuperar contraseña"
            setOnClickListener { openWebLogin() }
        }

        fun add(v: View, top: Int) {
            root.addView(
                v,
                LinearLayout.LayoutParams(
                    LinearLayout.LayoutParams.MATCH_PARENT,
                    LinearLayout.LayoutParams.WRAP_CONTENT
                ).apply { topMargin = dp(top) }
            )
        }

        add(title, 0)
        add(subtitle, 8)
        add(userInput, 28)
        add(passInput, 12)
        add(errorText, 12)
        add(loginButton, 20)
        add(progress, 12)
        add(forgotButton, 20)

        return root
    }

    private fun performLogin() {
        val username = userInput.text.toString().trim()
        val password = passInput.text.toString()
        if (username.isEmpty() || password.isEmpty()) {
            setError("Ingresa usuario y contraseña")
            return
        }
        setError(null)
        setLoading(true)
        Thread {
            val result = loginRequest(username, password)
            runOnUiThread {
                setLoading(false)
                if (result.ok && result.token != null) {
                    prefs.edit().putString(KEY_TOKEN, result.token).apply()
                    passInput.setText("")
                    showWebView(result.token)
                } else {
                    setError(result.error ?: "No se pudo iniciar sesión")
                }
            }
        }.start()
    }

    private data class LoginResult(val ok: Boolean, val token: String?, val error: String?)

    private fun loginRequest(username: String, password: String): LoginResult {
        var conn: HttpURLConnection? = null
        try {
            val c = (URL("$API_BASE/api/v1/auth/login").openConnection() as HttpURLConnection).apply {
                requestMethod = "POST"
                connectTimeout = 15000
                readTimeout = 15000
                doOutput = true
                setRequestProperty("Content-Type", "application/json")
                setRequestProperty("Accept", "application/json")
            }
            conn = c
            val body = JSONObject()
                .put("username", username)
                .put("password", password)
                .toString()
            c.outputStream.use { it.write(body.toByteArray(Charsets.UTF_8)) }
            val code = c.responseCode
            val stream = if (code in 200..299) c.inputStream else c.errorStream
            val text = stream?.bufferedReader(Charsets.UTF_8)?.use { it.readText() } ?: ""
            if (code in 200..299) {
                val token = JSONObject(text).optString("access_token", "")
                return if (token.isNotEmpty()) {
                    LoginResult(true, token, null)
                } else {
                    LoginResult(false, null, "Respuesta inválida del servidor")
                }
            }
            val detail = runCatching { JSONObject(text).optString("detail", "") }.getOrDefault("")
            return LoginResult(false, null, detail.ifEmpty { "Credenciales inválidas (HTTP $code)" })
        } catch (e: Exception) {
            return LoginResult(false, null, "Sin conexión al servidor: ${e.message}")
        } finally {
            conn?.disconnect()
        }
    }

    private enum class TokenStatus { VALID, INVALID, ERROR }

    private fun checkTokenAsync(token: String) {
        Thread {
            val status = checkToken(token)
            runOnUiThread {
                when (status) {
                    TokenStatus.VALID -> showWebView(token)
                    TokenStatus.INVALID -> {
                        prefs.edit().remove(KEY_TOKEN).apply()
                        showLogin()
                    }
                    TokenStatus.ERROR -> showWebView(token)
                }
            }
        }.start()
    }

    private fun checkToken(token: String): TokenStatus {
        var conn: HttpURLConnection? = null
        return try {
            val c = (URL("$API_BASE/api/v1/auth/me").openConnection() as HttpURLConnection).apply {
                requestMethod = "GET"
                connectTimeout = 15000
                readTimeout = 15000
                setRequestProperty("Authorization", "Bearer $token")
                setRequestProperty("Accept", "application/json")
            }
            conn = c
            when (c.responseCode) {
                in 200..299 -> TokenStatus.VALID
                401 -> TokenStatus.INVALID
                else -> TokenStatus.ERROR
            }
        } catch (e: Exception) {
            TokenStatus.ERROR
        } finally {
            conn?.disconnect()
        }
    }

    private fun showWebView(token: String) {
        runOnUiThread {
            setLoading(false)
            setError(null)
            loginView.visibility = View.GONE
            webView.visibility = View.VISIBLE
            val encoded = URLEncoder.encode(token, "UTF-8")
            val target = "$APP_URL?token=$encoded"
            if (webView.url != target) {
                webView.loadUrl(target)
            }
        }
    }

    private fun openWebLogin() {
        loginView.visibility = View.GONE
        webView.visibility = View.VISIBLE
        webView.loadUrl(APP_URL)
    }

    private fun showLogin() {
        runOnUiThread {
            webView.visibility = View.GONE
            loginView.visibility = View.VISIBLE
            setLoading(false)
            setError(null)
        }
    }

    private fun setLoading(loading: Boolean) {
        progress.visibility = if (loading) View.VISIBLE else View.GONE
        loginButton.isEnabled = !loading
        userInput.isEnabled = !loading
        passInput.isEnabled = !loading
    }

    private fun setError(message: String?) {
        if (message.isNullOrBlank()) {
            errorText.visibility = View.GONE
            errorText.text = ""
        } else {
            errorText.visibility = View.VISIBLE
            errorText.text = message
        }
    }

    @Deprecated("Deprecated in Java")
    override fun onBackPressed() {
        if (loginView.visibility == View.VISIBLE) {
            super.onBackPressed()
            return
        }
        if (webView.canGoBack()) webView.goBack() else super.onBackPressed()
    }

    inner class Bridge {
        @JavascriptInterface
        fun saveBase64(name: String, base64Data: String) {
            try {
                val bytes = Base64.decode(base64Data, Base64.DEFAULT)
                val safeName = if (name.isBlank()) "reporte.pdf" else name
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                    val values = ContentValues().apply {
                        put(MediaStore.Downloads.DISPLAY_NAME, safeName)
                        put(MediaStore.Downloads.MIME_TYPE, "application/pdf")
                        put(MediaStore.Downloads.IS_PENDING, 1)
                    }
                    val resolver = contentResolver
                    val uri = resolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values)
                    if (uri != null) {
                        resolver.openOutputStream(uri)?.use { it.write(bytes) }
                        values.clear()
                        values.put(MediaStore.Downloads.IS_PENDING, 0)
                        resolver.update(uri, values, null, null)
                    }
                } else {
                    val dir = Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS)
                    if (!dir.exists()) dir.mkdirs()
                    FileOutputStream(File(dir, safeName)).use { it.write(bytes) }
                }
                runOnUiThread {
                    Toast.makeText(this@MainActivity, "Guardado en Descargas: $safeName", Toast.LENGTH_LONG).show()
                }
            } catch (e: Exception) {
                runOnUiThread {
                    Toast.makeText(this@MainActivity, "Error al guardar PDF: ${e.message}", Toast.LENGTH_LONG).show()
                }
            }
        }

        @JavascriptInterface
        fun logout() {
            prefs.edit().remove(KEY_TOKEN).apply()
            passInput.setText("")
            showLogin()
        }
    }

    companion object {
        private const val TAG = "IoTWebView"
        private const val APP_URL = "https://lot-santiago.streamlit.app/"
        private const val API_BASE = "https://proyecto-production-bb60.up.railway.app"
        private const val PREFS_NAME = "iot_monitor"
        private const val KEY_TOKEN = "jwt_token"

        private const val INTERCEPT_JS = """
        (function() {
          if (window.__dlInstalled) return;
          window.__dlInstalled = true;
          function toB64(blob, cb) {
            var r = new FileReader();
            r.onloadend = function() {
              var res = r.result || '';
              var i = res.indexOf(',');
              cb(i >= 0 ? res.substring(i + 1) : res);
            };
            r.readAsDataURL(blob);
          }
          var origClick = HTMLAnchorElement.prototype.click;
          HTMLAnchorElement.prototype.click = function() {
            try {
              var name = this.download || 'reporte.pdf';
              var href = this.href || '';
              if (this.download && href.indexOf('blob:') === 0) {
                fetch(href).then(function(r){ return r.blob(); }).then(function(b){
                  toB64(b, function(b64){ AndroidBridge.saveBase64(name, b64); });
                });
                return;
              }
              if (this.download && href.indexOf('data:') === 0) {
                var i = href.indexOf(',');
                if (i >= 0) {
                  AndroidBridge.saveBase64(name, href.substring(i + 1));
                  return;
                }
              }
            } catch (e) {}
            return origClick.apply(this, arguments);
          };
          document.addEventListener('click', function(e) {
            var el = e.target;
            while (el && el !== document) {
              var txt = (el.innerText || el.textContent || '').trim();
              if (txt === 'Cerrar Sesión' || txt === 'Cerrar Sesion') {
                try { AndroidBridge.logout(); } catch (err) {}
                break;
              }
              el = el.parentElement;
            }
          }, true);
        })();
        """
    }
}

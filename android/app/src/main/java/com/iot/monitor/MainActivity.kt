package com.iot.monitor

import android.annotation.SuppressLint
import android.app.Activity
import android.app.DownloadManager
import android.content.ContentValues
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Environment
import android.provider.MediaStore
import android.util.Base64
import android.view.ViewGroup
import android.webkit.JavascriptInterface
import android.webkit.WebChromeClient
import android.webkit.WebResourceRequest
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Toast
import java.io.File
import java.io.FileOutputStream

class MainActivity : Activity() {

    private lateinit var webView: WebView

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        webView = WebView(this)
        webView.layoutParams = ViewGroup.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT,
            ViewGroup.LayoutParams.MATCH_PARENT
        )
        setContentView(webView)

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

        webView.addJavascriptInterface(PdfBridge(), "AndroidBridge")

        webView.webViewClient = object : WebViewClient() {
            override fun shouldOverrideUrlLoading(
                view: WebView?,
                request: WebResourceRequest?
            ): Boolean {
                val url = request?.url ?: return false
                val appHost = Uri.parse(APP_URL).host
                return if (url.host != null && url.host == appHost) {
                    false
                } else {
                    try {
                        startActivity(Intent(Intent.ACTION_VIEW, url))
                    } catch (_: Exception) {
                    }
                    true
                }
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

        if (savedInstanceState == null) {
            webView.loadUrl(APP_URL)
        } else {
            webView.restoreState(savedInstanceState)
        }
    }

    override fun onSaveInstanceState(outState: Bundle) {
        super.onSaveInstanceState(outState)
        webView.saveState(outState)
    }

    @Deprecated("Deprecated in Java")
    override fun onBackPressed() {
        if (webView.canGoBack()) webView.goBack() else super.onBackPressed()
    }

    inner class PdfBridge {
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
    }

    companion object {
        private const val APP_URL = "https://lot-santiago.streamlit.app/"

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
        })();
        """
    }
}

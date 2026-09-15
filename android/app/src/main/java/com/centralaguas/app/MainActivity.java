package com.centralaguas.app;

import android.Manifest;
import android.app.Activity;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.graphics.Insets;
import android.os.Build;
import android.os.Bundle;
import android.view.View;
import android.view.Window;
import android.view.WindowInsets;
import android.webkit.GeolocationPermissions;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;

import com.google.firebase.messaging.FirebaseMessaging;

public class MainActivity extends Activity {
    public static final String EXTRA_TARGET_URL = "com.centralaguas.app.TARGET_URL";
    private static final int LOCATION_PERMISSION_REQUEST = 1001;
    private static final int NOTIFICATION_PERMISSION_REQUEST = 1002;
    private WebView webView;
    private GeolocationPermissions.Callback pendingGeoCallback;
    private String pendingGeoOrigin;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        configureSystemBars();

        webView = new WebView(this);
        webView.setBackgroundColor(Color.WHITE);
        webView.setSystemUiVisibility(View.SYSTEM_UI_FLAG_LAYOUT_STABLE);
        webView.setFitsSystemWindows(true);
        applySystemBarInsets(webView);
        setContentView(webView);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.KITKAT_WATCH) {
            webView.requestApplyInsets();
        }

        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setDatabaseEnabled(true);
        settings.setGeolocationEnabled(true);
        settings.setLoadWithOverviewMode(true);
        settings.setUseWideViewPort(true);
        settings.setCacheMode(WebSettings.LOAD_NO_CACHE);
        webView.addJavascriptInterface(new CentralAguasBridge(this), "CentralAguasAndroid");
        webView.clearCache(true);
        webView.clearHistory();

        webView.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                return false;
            }

            @Override
            public void onPageFinished(WebView view, String url) {
                super.onPageFinished(view, url);
                flushHydrationActionsToWeb();
            }
        });

        webView.setWebChromeClient(new WebChromeClient() {
            @Override
            public void onGeolocationPermissionsShowPrompt(String origin, GeolocationPermissions.Callback callback) {
                if (checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED) {
                    callback.invoke(origin, true, false);
                    return;
                }
                pendingGeoOrigin = origin;
                pendingGeoCallback = callback;
                requestPermissions(
                    new String[] { Manifest.permission.ACCESS_FINE_LOCATION, Manifest.permission.ACCESS_COARSE_LOCATION },
                    LOCATION_PERMISSION_REQUEST
                );
            }
        });

        webView.loadUrl(resolveStartUrl(getIntent()));
        requestNotificationPermission();
        syncFcmToken();
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
        if (webView != null) {
            webView.loadUrl(resolveStartUrl(intent));
        }
    }

    private String resolveStartUrl(Intent intent) {
        String baseUrl = getString(R.string.app_start_url);
        if (intent == null) {
            return baseUrl;
        }
        String targetUrl = intent.getStringExtra(EXTRA_TARGET_URL);
        if (targetUrl == null || targetUrl.trim().isEmpty()) {
            targetUrl = intent.getStringExtra("url");
        }
        if (targetUrl == null || targetUrl.trim().isEmpty()) {
            return baseUrl;
        }
        targetUrl = targetUrl.trim();
        if (targetUrl.startsWith("https://app.centralaguas.com.br/")) {
            return targetUrl;
        }
        if (targetUrl.startsWith("/")) {
            return "https://app.centralaguas.com.br" + targetUrl;
        }
        return baseUrl;
    }

    private void configureSystemBars() {
        Window window = getWindow();
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.LOLLIPOP) {
            window.setStatusBarColor(Color.rgb(11, 76, 203));
            window.setNavigationBarColor(Color.WHITE);
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            window.getDecorView().setSystemUiVisibility(View.SYSTEM_UI_FLAG_LIGHT_NAVIGATION_BAR);
        }
    }

    private void applySystemBarInsets(View view) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.KITKAT_WATCH) {
            view.setOnApplyWindowInsetsListener((v, insets) -> {
                int top;
                int bottom;
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
                    Insets bars = insets.getInsets(WindowInsets.Type.systemBars());
                    top = bars.top;
                    bottom = bars.bottom;
                } else {
                    top = insets.getSystemWindowInsetTop();
                    bottom = insets.getSystemWindowInsetBottom();
                }
                v.setPadding(0, top, 0, bottom);
                return insets;
            });
        }
    }

    public boolean hasNotificationPermission() {
        return Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU
            || checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED;
    }

    public void requestNotificationPermissionFromBridge() {
        runOnUiThread(this::requestNotificationPermission);
    }

    private void flushHydrationActionsToWeb() {
        SharedPreferences prefs = getSharedPreferences(CentralAguasBridge.PREFS_NAME, Context.MODE_PRIVATE);
        int pendingDrinks = prefs.getInt(CentralAguasBridge.KEY_PENDING_DRINKS, 0);
        if (pendingDrinks <= 0 || webView == null) {
            return;
        }
        prefs.edit().putInt(CentralAguasBridge.KEY_PENDING_DRINKS, 0).apply();
        webView.evaluateJavascript(
            "window.centralAguasApplyNativeHydration && window.centralAguasApplyNativeHydration(" + pendingDrinks + ");",
            null
        );
    }

    private void requestNotificationPermission() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU
            && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[] { Manifest.permission.POST_NOTIFICATIONS }, NOTIFICATION_PERMISSION_REQUEST);
        }
    }

    private void syncFcmToken() {
        FirebaseMessaging.getInstance().getToken().addOnCompleteListener(task -> {
            if (!task.isSuccessful()) {
                Exception exception = task.getException();
                FcmTokenReporter.reportDiagnostic(
                    this,
                    "fcm_failed",
                    exception != null ? exception.toString() : "Firebase token task failed"
                );
                return;
            }
            if (task.getResult() == null) {
                FcmTokenReporter.reportDiagnostic(this, "fcm_empty", "Firebase returned an empty token");
                return;
            }
            FcmTokenReporter.report(this, task.getResult());
        });
    }

    @Override
    public void onBackPressed() {
        if (webView.canGoBack()) {
            webView.goBack();
            return;
        }
        super.onBackPressed();
    }

    @Override
    public void onRequestPermissionsResult(int requestCode, String[] permissions, int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        if (requestCode == LOCATION_PERMISSION_REQUEST && pendingGeoCallback != null && pendingGeoOrigin != null) {
            boolean granted = grantResults.length > 0 && grantResults[0] == PackageManager.PERMISSION_GRANTED;
            pendingGeoCallback.invoke(pendingGeoOrigin, granted, false);
            pendingGeoCallback = null;
            pendingGeoOrigin = null;
        }
        if (requestCode == NOTIFICATION_PERMISSION_REQUEST && webView != null) {
            webView.evaluateJavascript(
                "window.centralAguasRefreshNotificationStatus && window.centralAguasRefreshNotificationStatus();",
                null
            );
        }
    }
}

package com.centralaguas.app;

import android.content.Context;
import android.content.SharedPreferences;
import android.webkit.JavascriptInterface;

public class CentralAguasBridge {
    static final String PREFS_NAME = "central_aguas_hydration";
    static final String KEY_ENABLED = "enabled";
    static final String KEY_SCHEDULE = "schedule";
    static final String KEY_PENDING_DRINKS = "pending_drinks";

    private final MainActivity activity;

    CentralAguasBridge(MainActivity activity) {
        this.activity = activity;
    }

    @JavascriptInterface
    public boolean isNotificationPermissionGranted() {
        return activity.hasNotificationPermission();
    }

    @JavascriptInterface
    public boolean requestNotificationPermission() {
        activity.requestNotificationPermissionFromBridge();
        return activity.hasNotificationPermission();
    }

    @JavascriptInterface
    public void syncFcmToken() {
        activity.syncFcmToken();
    }

    @JavascriptInterface
    public String getDeviceId() {
        return FcmTokenReporter.deviceId(activity);
    }

    @JavascriptInterface
    public boolean scheduleHydrationReminders(String scheduleJson) {
        SharedPreferences prefs = activity.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE);
        prefs.edit()
            .putBoolean(KEY_ENABLED, true)
            .putString(KEY_SCHEDULE, scheduleJson)
            .apply();
        return HydrationReminderScheduler.schedule(activity, scheduleJson);
    }

    @JavascriptInterface
    public void cancelHydrationReminders() {
        activity.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            .edit()
            .putBoolean(KEY_ENABLED, false)
            .apply();
        HydrationReminderScheduler.cancel(activity);
    }
}

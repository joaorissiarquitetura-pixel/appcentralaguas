package com.centralaguas.app;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;

public class HydrationBootReceiver extends BroadcastReceiver {
    @Override
    public void onReceive(Context context, Intent intent) {
        String action = intent != null ? intent.getAction() : "";
        boolean enabled = context
            .getSharedPreferences(CentralAguasBridge.PREFS_NAME, Context.MODE_PRIVATE)
            .getBoolean(CentralAguasBridge.KEY_ENABLED, false);
        if (!enabled) {
            return;
        }
        if (Intent.ACTION_BOOT_COMPLETED.equals(action) || Intent.ACTION_MY_PACKAGE_REPLACED.equals(action)) {
            HydrationReminderScheduler.rescheduleSaved(context);
        }
    }
}

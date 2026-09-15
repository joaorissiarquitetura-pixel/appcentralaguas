package com.centralaguas.app;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.os.Build;

public class HydrationReminderReceiver extends BroadcastReceiver {
    static final String ACTION_REMIND = "com.centralaguas.app.HYDRATION_REMIND";
    static final String ACTION_DRANK = "com.centralaguas.app.HYDRATION_DRANK";
    static final String EXTRA_INDEX = "index";
    static final String EXTRA_TOTAL = "total";
    static final String EXTRA_CUP_ML = "cup_ml";
    static final String EXTRA_URL = "url";

    private static final String CHANNEL_ID = "central_aguas_hydration";
    private static final int NOTIFICATION_ID = 55001;

    @Override
    public void onReceive(Context context, Intent intent) {
        String action = intent != null ? intent.getAction() : "";
        if (ACTION_DRANK.equals(action)) {
            recordDrink(context);
            NotificationManager manager = (NotificationManager) context.getSystemService(Context.NOTIFICATION_SERVICE);
            manager.cancel(NOTIFICATION_ID);
            return;
        }
        if (ACTION_REMIND.equals(action)) {
            showReminder(context, intent);
        }
    }

    private void recordDrink(Context context) {
        SharedPreferences prefs = context.getSharedPreferences(CentralAguasBridge.PREFS_NAME, Context.MODE_PRIVATE);
        int pending = prefs.getInt(CentralAguasBridge.KEY_PENDING_DRINKS, 0);
        prefs.edit().putInt(CentralAguasBridge.KEY_PENDING_DRINKS, pending + 1).apply();
    }

    private void showReminder(Context context, Intent sourceIntent) {
        NotificationManager manager = (NotificationManager) context.getSystemService(Context.NOTIFICATION_SERVICE);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            NotificationChannel channel = new NotificationChannel(
                CHANNEL_ID,
                "Lembretes de água",
                NotificationManager.IMPORTANCE_DEFAULT
            );
            manager.createNotificationChannel(channel);
        }

        int index = sourceIntent.getIntExtra(EXTRA_INDEX, 1);
        int total = sourceIntent.getIntExtra(EXTRA_TOTAL, 1);
        int cupMl = sourceIntent.getIntExtra(EXTRA_CUP_ML, 300);
        String url = sourceIntent.getStringExtra(EXTRA_URL);
        if (url == null || url.trim().isEmpty()) {
            url = "/app?screen=gotinha";
        }

        Intent openIntent = new Intent(context, MainActivity.class);
        openIntent.putExtra(MainActivity.EXTRA_TARGET_URL, url);
        openIntent.addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP);
        PendingIntent contentIntent = PendingIntent.getActivity(
            context,
            55100,
            openIntent,
            PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE
        );

        Intent drankIntent = new Intent(context, HydrationReminderReceiver.class);
        drankIntent.setAction(ACTION_DRANK);
        PendingIntent drankPendingIntent = PendingIntent.getBroadcast(
            context,
            55101,
            drankIntent,
            PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE
        );

        Notification.Builder builder = Build.VERSION.SDK_INT >= Build.VERSION_CODES.O
            ? new Notification.Builder(context, CHANNEL_ID)
            : new Notification.Builder(context);

        builder
            .setSmallIcon(R.mipmap.ic_launcher)
            .setContentTitle("Hora da água")
            .setContentText("Beba 1 copo de " + cupMl + " ml. Aviso " + index + " de " + total + ".")
            .setContentIntent(contentIntent)
            .setAutoCancel(true)
            .addAction(R.mipmap.ic_launcher, "Bebi água", drankPendingIntent);

        manager.notify(NOTIFICATION_ID, builder.build());
    }
}

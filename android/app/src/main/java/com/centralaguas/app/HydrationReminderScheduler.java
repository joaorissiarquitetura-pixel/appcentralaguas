package com.centralaguas.app;

import android.app.AlarmManager;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.Calendar;

public final class HydrationReminderScheduler {
    private static final int MAX_REMINDERS = 24;
    private static final int REQUEST_BASE = 44000;

    private HydrationReminderScheduler() {}

    public static boolean schedule(Context context, String scheduleJson) {
        cancel(context);
        try {
            JSONObject payload = new JSONObject(scheduleJson);
            JSONArray times = payload.optJSONArray("times");
            int cupMl = payload.optInt("cupMl", 300);
            int total = payload.optInt("count", times != null ? times.length() : 0);
            String url = payload.optString("url", "/app?screen=gotinha");
            String title = payload.optString("title", "Hora de beber água");
            String body = payload.optString("body", "");
            if (times == null || times.length() == 0) {
                return false;
            }

            AlarmManager alarmManager = (AlarmManager) context.getSystemService(Context.ALARM_SERVICE);
            long now = System.currentTimeMillis();
            int scheduled = 0;
            for (int index = 0; index < Math.min(times.length(), MAX_REMINDERS); index++) {
                String time = times.optString(index, "");
                long triggerAt = triggerAtToday(time);
                if (triggerAt <= now) {
                    continue;
                }
                Intent intent = new Intent(context, HydrationReminderReceiver.class);
                intent.setAction(HydrationReminderReceiver.ACTION_REMIND);
                intent.putExtra(HydrationReminderReceiver.EXTRA_INDEX, index + 1);
                intent.putExtra(HydrationReminderReceiver.EXTRA_TOTAL, total);
                intent.putExtra(HydrationReminderReceiver.EXTRA_CUP_ML, cupMl);
                intent.putExtra(HydrationReminderReceiver.EXTRA_URL, url);
                intent.putExtra(HydrationReminderReceiver.EXTRA_TITLE, title);
                intent.putExtra(HydrationReminderReceiver.EXTRA_BODY, body);
                PendingIntent pendingIntent = PendingIntent.getBroadcast(
                    context,
                    REQUEST_BASE + index,
                    intent,
                    PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE
                );
                alarmManager.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, triggerAt, pendingIntent);
                scheduled++;
            }
            return scheduled > 0;
        } catch (Exception ignored) {
            return false;
        }
    }

    public static void cancel(Context context) {
        AlarmManager alarmManager = (AlarmManager) context.getSystemService(Context.ALARM_SERVICE);
        for (int index = 0; index < MAX_REMINDERS; index++) {
            Intent intent = new Intent(context, HydrationReminderReceiver.class);
            intent.setAction(HydrationReminderReceiver.ACTION_REMIND);
            PendingIntent pendingIntent = PendingIntent.getBroadcast(
                context,
                REQUEST_BASE + index,
                intent,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE
            );
            alarmManager.cancel(pendingIntent);
        }
    }

    public static void rescheduleSaved(Context context) {
        String scheduleJson = context
            .getSharedPreferences(CentralAguasBridge.PREFS_NAME, Context.MODE_PRIVATE)
            .getString(CentralAguasBridge.KEY_SCHEDULE, "");
        if (!scheduleJson.isEmpty()) {
            schedule(context, scheduleJson);
        }
    }

    private static long triggerAtToday(String time) {
        String[] parts = time.split(":");
        if (parts.length != 2) {
            return 0;
        }
        Calendar calendar = Calendar.getInstance();
        calendar.set(Calendar.HOUR_OF_DAY, Integer.parseInt(parts[0]));
        calendar.set(Calendar.MINUTE, Integer.parseInt(parts[1]));
        calendar.set(Calendar.SECOND, 0);
        calendar.set(Calendar.MILLISECOND, 0);
        return calendar.getTimeInMillis();
    }
}

package com.centralaguas.app;

import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.Intent;
import android.os.Build;

import com.google.firebase.messaging.FirebaseMessagingService;
import com.google.firebase.messaging.RemoteMessage;

public class CentralAguasMessagingService extends FirebaseMessagingService {
    private static final String CHANNEL_ID = "central_aguas_alerts";

    @Override
    public void onNewToken(String token) {
        super.onNewToken(token);
        FcmTokenReporter.report(this, token);
    }

    @Override
    public void onMessageReceived(RemoteMessage message) {
        super.onMessageReceived(message);
        String title = message.getNotification() != null ? message.getNotification().getTitle() : message.getData().get("title");
        String body = message.getNotification() != null ? message.getNotification().getBody() : message.getData().get("body");
        String url = message.getData().get("url");
        showNotification(
            title != null ? title : "Central Águas",
            body != null ? body : "Você tem uma novidade no app.",
            url != null ? url : "/app"
        );
    }

    private void showNotification(String title, String body, String url) {
        NotificationManager manager = (NotificationManager) getSystemService(NOTIFICATION_SERVICE);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            NotificationChannel channel = new NotificationChannel(
                CHANNEL_ID,
                "Central Águas",
                NotificationManager.IMPORTANCE_HIGH
            );
            channel.enableVibration(true);
            manager.createNotificationChannel(channel);
        }

        Intent intent = new Intent(this, MainActivity.class);
        intent.putExtra(MainActivity.EXTRA_TARGET_URL, url);
        intent.addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP);
        PendingIntent pendingIntent = PendingIntent.getActivity(
            this,
            0,
            intent,
            PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT
        );

        android.app.Notification.Builder builder = Build.VERSION.SDK_INT >= Build.VERSION_CODES.O
            ? new android.app.Notification.Builder(this, CHANNEL_ID)
            : new android.app.Notification.Builder(this);

        builder
            .setSmallIcon(R.drawable.ic_notification_drop)
            .setContentTitle(title)
            .setContentText(body)
            .setStyle(new android.app.Notification.BigTextStyle().bigText(body))
            .setContentIntent(pendingIntent)
            .setPriority(android.app.Notification.PRIORITY_HIGH)
            .setDefaults(android.app.Notification.DEFAULT_ALL)
            .setAutoCancel(true);

        manager.notify((int) System.currentTimeMillis(), builder.build());
    }
}

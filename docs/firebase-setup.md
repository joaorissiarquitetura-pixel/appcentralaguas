# Firebase setup

Projeto Firebase:

```text
central-aguas-app
```

App Android:

```text
com.centralaguas.app
```

## 1. Login nas CLIs

```powershell
firebase login
gcloud auth login
gcloud config set project central-aguas-app
```

## 2. Registrar app Android

```powershell
.\scripts\firebase_android_setup.ps1
```

Depois copie o App ID Android exibido e rode:

```powershell
firebase apps:sdkconfig ANDROID SEU_FIREBASE_APP_ID --project central-aguas-app > android/app/google-services.json
```

## 3. Credencial do backend para enviar FCM

No Firebase Console:

1. Abra Project settings.
2. Abra Service accounts.
3. Clique em Generate new private key.
4. Copie o JSON inteiro para o secret do servidor:

```env
FIREBASE_SERVICE_ACCOUNT_JSON={...json inteiro...}
```

## 4. Hosting

O app e backend são FastAPI/Jinja, então o Firebase Hosting encaminha as rotas para Cloud Run.

```powershell
.\scripts\firebase_deploy_hosting.ps1
```

O arquivo `firebase.json` já está configurado para encaminhar tudo para:

```text
serviceId: central-aguas-app
region: us-central1
```

## 5. Build do APK com FCM

Depois que `android/app/google-services.json` existir, gere o APK pela pasta `android` usando Gradle/Android Studio.

Para produção, assine com uma chave release, não com a chave debug.

package com.sproutspeak.kids;

import android.Manifest;
import android.annotation.SuppressLint;
import android.app.Activity;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.os.Bundle;
import android.speech.RecognizerIntent;
import android.speech.tts.TextToSpeech;
import android.webkit.JavascriptInterface;
import android.webkit.WebView;
import android.webkit.WebViewClient;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Locale;

public class MainActivity extends Activity {
    private static final int REQ_SPEECH = 1001;
    private static final int REQ_MIC = 1002;
    private WebView webView;
    private TextToSpeech tts;
    private String speechTarget = "chat";
    private boolean pendingSpeech = false;

    @SuppressLint({"SetJavaScriptEnabled", "AddJavascriptInterface"})
    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        webView = new WebView(this);
        setContentView(webView);
        webView.getSettings().setJavaScriptEnabled(true);
        webView.getSettings().setDomStorageEnabled(true);
        webView.getSettings().setAllowFileAccess(true);
        webView.getSettings().setMediaPlaybackRequiresUserGesture(false);
        webView.setWebViewClient(new WebViewClient());
        webView.addJavascriptInterface(new AppBridge(), "AndroidBridge");
        tts = new TextToSpeech(this, status -> {
            if (status == TextToSpeech.SUCCESS) {
                tts.setLanguage(Locale.US);
                tts.setSpeechRate(0.82f);
                tts.setPitch(1.05f);
            }
        });
        webView.loadUrl("file:///android_asset/index.html");
    }

    public class AppBridge {
        @JavascriptInterface public void startSpeech(String target) {
            runOnUiThread(() -> {
                speechTarget = target == null ? "chat" : target;
                if (android.os.Build.VERSION.SDK_INT >= 23 && checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
                    pendingSpeech = true;
                    requestPermissions(new String[]{Manifest.permission.RECORD_AUDIO}, REQ_MIC);
                } else launchSpeech();
            });
        }

        @JavascriptInterface public void speak(String text) {
            runOnUiThread(() -> {
                if (tts != null && text != null) tts.speak(text, TextToSpeech.QUEUE_FLUSH, null, "sprout");
            });
        }

        @JavascriptInterface public void chat(String apiKey, String model, String messagesJson, String requestId) {
            new Thread(() -> doDeepSeek(apiKey, model, messagesJson, requestId)).start();
        }

        @JavascriptInterface public String deviceInfo() {
            return "Android " + android.os.Build.VERSION.RELEASE + " / SDK " + android.os.Build.VERSION.SDK_INT;
        }
    }

    private void launchSpeech() {
        try {
            Intent i = new Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH);
            i.putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM);
            i.putExtra(RecognizerIntent.EXTRA_LANGUAGE, "en-US");
            i.putExtra(RecognizerIntent.EXTRA_PROMPT, "Speak English");
            i.putExtra(RecognizerIntent.EXTRA_MAX_RESULTS, 1);
            startActivityForResult(i, REQ_SPEECH);
        } catch (Exception e) {
            js("window.onNativeSpeechError && window.onNativeSpeechError(" + JSONObject.quote("当前设备没有可用的语音识别服务") + ");");
        }
    }

    @Override public void onRequestPermissionsResult(int requestCode, String[] permissions, int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        if (requestCode == REQ_MIC) {
            if (grantResults.length > 0 && grantResults[0] == PackageManager.PERMISSION_GRANTED && pendingSpeech) launchSpeech();
            else js("window.onNativeSpeechError && window.onNativeSpeechError('需要麦克风权限才能语音练习');");
            pendingSpeech = false;
        }
    }

    @Override protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode == REQ_SPEECH) {
            if (resultCode == RESULT_OK && data != null) {
                ArrayList<String> rs = data.getStringArrayListExtra(RecognizerIntent.EXTRA_RESULTS);
                float[] cs = data.getFloatArrayExtra(RecognizerIntent.EXTRA_CONFIDENCE_SCORES);
                String text = rs != null && !rs.isEmpty() ? rs.get(0) : "";
                double confidence = cs != null && cs.length > 0 ? cs[0] : -1;
                js("window.onNativeSpeech && window.onNativeSpeech(" + JSONObject.quote(speechTarget) + "," + JSONObject.quote(text) + "," + confidence + ");");
            } else {
                js("window.onNativeSpeechError && window.onNativeSpeechError('未识别到有效语音');");
            }
        }
    }

    private void doDeepSeek(String apiKey, String model, String messagesJson, String requestId) {
        HttpURLConnection conn = null;
        try {
            if (apiKey == null || apiKey.trim().isEmpty()) throw new Exception("请先在设置中填写 DeepSeek API Key");
            String useModel = (model == null || model.trim().isEmpty()) ? "deepseek-chat" : model.trim();
            JSONObject body = new JSONObject();
            body.put("model", useModel);
            body.put("messages", new JSONArray(messagesJson));
            body.put("stream", false);
            body.put("temperature", 0.7);

            URL u = new URL("https://api.deepseek.com/chat/completions");
            conn = (HttpURLConnection) u.openConnection();
            conn.setConnectTimeout(20000);
            conn.setReadTimeout(60000);
            conn.setRequestMethod("POST");
            conn.setDoOutput(true);
            conn.setRequestProperty("Content-Type", "application/json");
            conn.setRequestProperty("Authorization", "Bearer " + apiKey.trim());
            try (OutputStream os = conn.getOutputStream()) {
                os.write(body.toString().getBytes(StandardCharsets.UTF_8));
            }
            int code = conn.getResponseCode();
            InputStream in = code >= 200 && code < 300 ? conn.getInputStream() : conn.getErrorStream();
            String raw = readAll(in);
            if (code < 200 || code >= 300) {
                String msg = raw;
                try { msg = new JSONObject(raw).optJSONObject("error").optString("message", raw); } catch (Exception ignored) {}
                throw new Exception("DeepSeek API " + code + ": " + msg);
            }
            JSONObject data = new JSONObject(raw);
            String content = data.getJSONArray("choices").getJSONObject(0).getJSONObject("message").optString("content", "");
            callbackChat(requestId, true, content);
        } catch (Exception e) {
            callbackChat(requestId, false, e.getMessage() == null ? "请求失败" : e.getMessage());
        } finally {
            if (conn != null) conn.disconnect();
        }
    }

    private String readAll(InputStream in) throws Exception {
        if (in == null) return "";
        BufferedReader br = new BufferedReader(new InputStreamReader(in, StandardCharsets.UTF_8));
        StringBuilder sb = new StringBuilder();
        String line;
        while ((line = br.readLine()) != null) sb.append(line).append('\n');
        return sb.toString();
    }

    private void callbackChat(String id, boolean ok, String value) {
        js("window.onAndroidChat && window.onAndroidChat(" + JSONObject.quote(id == null ? "" : id) + "," + ok + "," + JSONObject.quote(value == null ? "" : value) + ");");
    }

    private void js(String script) {
        runOnUiThread(() -> webView.evaluateJavascript(script, null));
    }

    @Override public void onBackPressed() {
        if (webView != null && webView.canGoBack()) webView.goBack(); else super.onBackPressed();
    }

    @Override protected void onDestroy() {
        if (tts != null) { tts.stop(); tts.shutdown(); }
        if (webView != null) webView.destroy();
        super.onDestroy();
    }
}

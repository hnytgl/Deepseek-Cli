package com.sproutspeak.kids;

import android.Manifest;
import android.annotation.SuppressLint;
import android.app.Activity;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.speech.RecognizerIntent;
import android.speech.tts.TextToSpeech;
import android.speech.tts.UtteranceProgressListener;
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
    private static final int REQ_MIC = 1002;
    private static final int REQ_SPEECH = 1003;
    private static final String MODEL = "deepseek-v4-flash";
    private static final String PREFS = "sproutspeak_local";
    private static final String KEY_NAME = "deepseek_api_key";
    private static final long MIC_DEBOUNCE_MS = 1200L;

    private WebView webView;
    private TextToSpeech tts;
    private SharedPreferences prefs;
    private final Handler mainHandler = new Handler(Looper.getMainLooper());
    private String speechTarget = "chat";
    private boolean pendingSpeech = false;
    private boolean speechInFlight = false;
    private boolean ttsReady = false;
    private long lastMicLaunchAt = 0L;

    @SuppressLint({"SetJavaScriptEnabled", "AddJavascriptInterface"})
    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        prefs = getSharedPreferences(PREFS, MODE_PRIVATE);
        webView = new WebView(this);
        setContentView(webView);
        webView.getSettings().setJavaScriptEnabled(true);
        webView.getSettings().setDomStorageEnabled(true);
        webView.getSettings().setAllowFileAccess(true);
        webView.getSettings().setMediaPlaybackRequiresUserGesture(false);
        webView.setWebViewClient(new WebViewClient());
        webView.addJavascriptInterface(new AppBridge(), "AndroidBridge");
        initTts();
        webView.loadUrl("file:///android_asset/index.html");
    }

    private void initTts() {
        tts = new TextToSpeech(this, status -> {
            if (status == TextToSpeech.SUCCESS) {
                ttsReady = true;
                tts.setLanguage(Locale.US);
                tts.setSpeechRate(0.86f);
                tts.setPitch(1.02f);
                tts.setOnUtteranceProgressListener(new UtteranceProgressListener() {
                    @Override public void onStart(String utteranceId) {
                        js("window.onNativeTtsStart && window.onNativeTtsStart();");
                    }
                    @Override public void onDone(String utteranceId) {
                        js("window.onNativeTtsDone && window.onNativeTtsDone();");
                    }
                    @Override public void onError(String utteranceId) {
                        js("window.onNativeTtsDone && window.onNativeTtsDone();");
                    }
                });
            } else {
                ttsReady = false;
                js("window.onNativeTtsError && window.onNativeTtsError('系统英语朗读初始化失败');");
            }
        });
    }

    private boolean speechActivityAvailable() {
        try {
            Intent i = new Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH);
            return i.resolveActivity(getPackageManager()) != null;
        } catch (Exception e) {
            return false;
        }
    }

    private void launchSpeechOnce() {
        if (speechInFlight) {
            js("window.onNativeSpeechError && window.onNativeSpeechError('正在听上一句，请先完成这次回答');");
            return;
        }
        if (!speechActivityAvailable()) {
            js("window.onNativeSpeechError && window.onNativeSpeechError('当前平板没有可用的系统英语语音输入服务');");
            return;
        }

        long now = SystemClock.elapsedRealtime();
        long wait = MIC_DEBOUNCE_MS - (now - lastMicLaunchAt);
        if (wait > 0) {
            js("window.onNativeSpeechState && window.onNativeSpeechState('processing');");
            mainHandler.postDelayed(this::launchSpeechOnce, wait);
            return;
        }

        try {
            if (tts != null) tts.stop();
            Intent i = new Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH);
            i.putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM);
            i.putExtra(RecognizerIntent.EXTRA_LANGUAGE, "en-US");
            i.putExtra(RecognizerIntent.EXTRA_LANGUAGE_PREFERENCE, "en-US");
            i.putExtra(RecognizerIntent.EXTRA_PROMPT, "Speak English");
            i.putExtra(RecognizerIntent.EXTRA_MAX_RESULTS, 3);
            i.putExtra(RecognizerIntent.EXTRA_PREFER_OFFLINE, false);
            speechInFlight = true;
            lastMicLaunchAt = now;
            js("window.onNativeSpeechState && window.onNativeSpeechState('ready');");
            startActivityForResult(i, REQ_SPEECH);
        } catch (Exception e) {
            speechInFlight = false;
            js("window.onNativeSpeechError && window.onNativeSpeechError(" + JSONObject.quote("语音输入启动失败：" + e.getMessage()) + ");");
        }
    }

    public class AppBridge {
        @JavascriptInterface public void startSpeech(String target) {
            runOnUiThread(() -> {
                speechTarget = target == null ? "chat" : target;
                if (android.os.Build.VERSION.SDK_INT >= 23 && checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
                    pendingSpeech = true;
                    requestPermissions(new String[]{Manifest.permission.RECORD_AUDIO}, REQ_MIC);
                } else {
                    launchSpeechOnce();
                }
            });
        }

        @JavascriptInterface public void stopSpeech() {
            // 单次系统语音输入模式不做强制中断，避免制造 RecognitionService busy。
        }

        @JavascriptInterface public void speak(String text) {
            runOnUiThread(() -> {
                if (tts != null && ttsReady && text != null && !text.trim().isEmpty()) {
                    tts.speak(text, TextToSpeech.QUEUE_FLUSH, null, "sproutspeak_turn");
                } else {
                    js("window.onNativeTtsDone && window.onNativeTtsDone();");
                }
            });
        }

        @JavascriptInterface public String saveApiKey(String key) {
            if (key == null) return "API Key 为空";
            String clean = key.replaceAll("\\s+", "").trim();
            if (clean.length() < 20) return "API Key 看起来不完整，请重新复制粘贴";
            prefs.edit().putString(KEY_NAME, clean).apply();
            return "OK";
        }

        @JavascriptInterface public boolean hasApiKey() {
            return !prefs.getString(KEY_NAME, "").trim().isEmpty();
        }

        @JavascriptInterface public void clearApiKey() {
            prefs.edit().remove(KEY_NAME).apply();
        }

        @JavascriptInterface public String modelName() { return MODEL; }
        @JavascriptInterface public boolean speechAvailable() { return speechActivityAvailable(); }
        @JavascriptInterface public boolean ttsAvailable() { return ttsReady; }
        @JavascriptInterface public void chat(String messagesJson, String requestId) { new Thread(() -> doDeepSeek(messagesJson, requestId)).start(); }
    }

    @Override public void onRequestPermissionsResult(int requestCode, String[] permissions, int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        if (requestCode == REQ_MIC) {
            if (grantResults.length > 0 && grantResults[0] == PackageManager.PERMISSION_GRANTED && pendingSpeech) {
                launchSpeechOnce();
            } else {
                js("window.onNativeSpeechError && window.onNativeSpeechError('需要麦克风权限才能进行口语练习');");
            }
            pendingSpeech = false;
        }
    }

    @Override protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode == REQ_SPEECH) {
            speechInFlight = false;
            if (resultCode == RESULT_OK && data != null) {
                ArrayList<String> rs = data.getStringArrayListExtra(RecognizerIntent.EXTRA_RESULTS);
                float[] cs = data.getFloatArrayExtra(RecognizerIntent.EXTRA_CONFIDENCE_SCORES);
                String text = rs != null && !rs.isEmpty() ? rs.get(0) : "";
                double confidence = cs != null && cs.length > 0 ? cs[0] : -1;
                if (text == null || text.trim().isEmpty()) {
                    js("window.onNativeSpeechError && window.onNativeSpeechError('没有识别到回答，请再试一次');");
                } else {
                    js("window.onNativeSpeech && window.onNativeSpeech(" + JSONObject.quote(speechTarget) + "," + JSONObject.quote(text.trim()) + "," + confidence + ");");
                }
            } else {
                js("window.onNativeSpeechError && window.onNativeSpeechError('这次没有收到语音结果，请再按一次麦克风');");
            }
        }
    }

    private void doDeepSeek(String messagesJson, String requestId) {
        HttpURLConnection conn = null;
        try {
            String apiKey = prefs.getString(KEY_NAME, "").trim();
            if (apiKey.isEmpty()) throw new Exception("请先在设置中保存 DeepSeek API Key");
            JSONObject body = new JSONObject();
            body.put("model", MODEL);
            body.put("messages", new JSONArray(messagesJson));
            body.put("stream", false);
            body.put("temperature", 0.7);
            URL u = new URL("https://api.deepseek.com/chat/completions");
            conn = (HttpURLConnection) u.openConnection();
            conn.setConnectTimeout(20000);
            conn.setReadTimeout(60000);
            conn.setRequestMethod("POST");
            conn.setDoOutput(true);
            conn.setRequestProperty("Content-Type", "application/json; charset=utf-8");
            conn.setRequestProperty("Accept", "application/json");
            conn.setRequestProperty("Authorization", "Bearer " + apiKey);
            try (OutputStream os = conn.getOutputStream()) {
                os.write(body.toString().getBytes(StandardCharsets.UTF_8));
            }
            int code = conn.getResponseCode();
            InputStream in = code >= 200 && code < 300 ? conn.getInputStream() : conn.getErrorStream();
            String raw = readAll(in);
            if (code < 200 || code >= 300) {
                String msg = raw;
                try {
                    JSONObject err = new JSONObject(raw).optJSONObject("error");
                    if (err != null) msg = err.optString("message", raw);
                } catch (Exception ignored) {}
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
        runOnUiThread(() -> {
            if (webView != null) webView.evaluateJavascript(script, null);
        });
    }

    @Override protected void onDestroy() {
        mainHandler.removeCallbacksAndMessages(null);
        if (tts != null) { tts.stop(); tts.shutdown(); }
        if (webView != null) webView.destroy();
        super.onDestroy();
    }
}

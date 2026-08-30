package com.sproutspeak.kids;

import android.Manifest;
import android.annotation.SuppressLint;
import android.app.Activity;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.media.MediaRecorder;
import android.os.Bundle;
import android.speech.tts.TextToSpeech;
import android.speech.tts.UtteranceProgressListener;
import android.webkit.JavascriptInterface;
import android.webkit.WebView;
import android.webkit.WebViewClient;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.File;
import java.io.FileInputStream;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.Locale;

public class MainActivity extends Activity {
    private static final int REQ_MIC = 1002;
    private static final String MODEL = "deepseek-v4-flash";
    private static final String ASR_MODEL = "FunAudioLLM/SenseVoiceSmall";
    private static final String PREFS = "sproutspeak_local";
    private static final String KEY_DEEPSEEK = "deepseek_api_key";
    private static final String KEY_SPEECH = "siliconflow_speech_key";

    private WebView webView;
    private SharedPreferences prefs;
    private TextToSpeech tts;
    private boolean ttsReady = false;

    private MediaRecorder recorder;
    private File recordingFile;
    private boolean recording = false;
    private boolean pendingRecord = false;
    private String speechTarget = "chat";
    private long recordStartedAt = 0L;

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
                js("window.onNativeTtsError && window.onNativeTtsError('系统英语朗读不可用，但仍可使用文字对话');");
            }
        });
    }

    public class AppBridge {
        @JavascriptInterface public String saveApiKey(String key) {
            if (key == null) return "DeepSeek API Key 为空";
            String clean = key.replaceAll("\\s+", "").trim();
            if (clean.length() < 20) return "DeepSeek API Key 看起来不完整";
            prefs.edit().putString(KEY_DEEPSEEK, clean).apply();
            return "OK";
        }

        @JavascriptInterface public boolean hasApiKey() {
            return !prefs.getString(KEY_DEEPSEEK, "").trim().isEmpty();
        }

        @JavascriptInterface public String saveSpeechApiKey(String key) {
            if (key == null) return "语音 API Key 为空";
            String clean = key.replaceAll("\\s+", "").trim();
            if (clean.length() < 20) return "语音 API Key 看起来不完整";
            prefs.edit().putString(KEY_SPEECH, clean).apply();
            return "OK";
        }

        @JavascriptInterface public boolean hasSpeechApiKey() {
            return !prefs.getString(KEY_SPEECH, "").trim().isEmpty();
        }

        @JavascriptInterface public void clearSpeechApiKey() {
            prefs.edit().remove(KEY_SPEECH).apply();
        }

        @JavascriptInterface public String modelName() { return MODEL; }
        @JavascriptInterface public String speechModelName() { return ASR_MODEL; }
        @JavascriptInterface public boolean speechAvailable() { return true; }
        @JavascriptInterface public boolean ttsAvailable() { return ttsReady; }

        @JavascriptInterface public void startSpeech(String target) {
            runOnUiThread(() -> requestStartRecording(target));
        }

        @JavascriptInterface public void stopSpeech() {
            runOnUiThread(() -> stopRecordingAndTranscribe());
        }

        @JavascriptInterface public void speak(String text) {
            runOnUiThread(() -> {
                if (recording) cancelRecording();
                if (tts != null && ttsReady && text != null && !text.trim().isEmpty()) {
                    tts.speak(text, TextToSpeech.QUEUE_FLUSH, null, "sproutspeak_turn");
                } else {
                    js("window.onNativeTtsDone && window.onNativeTtsDone();");
                }
            });
        }

        @JavascriptInterface public void chat(String messagesJson, String requestId) {
            new Thread(() -> doDeepSeek(messagesJson, requestId)).start();
        }
    }

    private void requestStartRecording(String target) {
        speechTarget = target == null ? "chat" : target;
        if (recording) return;
        if (android.os.Build.VERSION.SDK_INT >= 23 && checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            pendingRecord = true;
            requestPermissions(new String[]{Manifest.permission.RECORD_AUDIO}, REQ_MIC);
            return;
        }
        beginRecording();
    }

    private void beginRecording() {
        try {
            if (tts != null) tts.stop();
            cancelRecording();
            recordingFile = new File(getCacheDir(), "sproutspeak_" + System.currentTimeMillis() + ".m4a");
            recorder = new MediaRecorder();
            recorder.setAudioSource(MediaRecorder.AudioSource.MIC);
            recorder.setOutputFormat(MediaRecorder.OutputFormat.MPEG_4);
            recorder.setAudioEncoder(MediaRecorder.AudioEncoder.AAC);
            recorder.setAudioEncodingBitRate(64000);
            recorder.setAudioSamplingRate(16000);
            recorder.setOutputFile(recordingFile.getAbsolutePath());
            recorder.prepare();
            recorder.start();
            recordStartedAt = System.currentTimeMillis();
            recording = true;
            js("window.onNativeSpeechState && window.onNativeSpeechState('recording');");
        } catch (Exception e) {
            recording = false;
            safeReleaseRecorder();
            js("window.onNativeSpeechError && window.onNativeSpeechError(" + JSONObject.quote("无法开始录音：" + safeMessage(e)) + ");");
        }
    }

    private void stopRecordingAndTranscribe() {
        if (!recording || recorder == null) return;
        long duration = System.currentTimeMillis() - recordStartedAt;
        File file = recordingFile;
        try {
            recorder.stop();
        } catch (RuntimeException e) {
            safeReleaseRecorder();
            recording = false;
            if (file != null) file.delete();
            js("window.onNativeSpeechError && window.onNativeSpeechError('录音太短，请按住麦克风说完一句再松开');");
            return;
        }
        safeReleaseRecorder();
        recording = false;
        if (duration < 500 || file == null || !file.exists() || file.length() < 1000) {
            if (file != null) file.delete();
            js("window.onNativeSpeechError && window.onNativeSpeechError('录音太短，请至少说半秒以上');");
            return;
        }
        js("window.onNativeSpeechState && window.onNativeSpeechState('processing');");
        final String target = speechTarget;
        new Thread(() -> transcribeFile(file, target)).start();
    }

    private void cancelRecording() {
        if (recorder != null) {
            try { recorder.stop(); } catch (Exception ignored) {}
            safeReleaseRecorder();
        }
        recording = false;
        if (recordingFile != null && recordingFile.exists()) recordingFile.delete();
        recordingFile = null;
    }

    private void safeReleaseRecorder() {
        if (recorder != null) {
            try { recorder.reset(); } catch (Exception ignored) {}
            try { recorder.release(); } catch (Exception ignored) {}
            recorder = null;
        }
    }

    private void transcribeFile(File file, String target) {
        HttpURLConnection conn = null;
        try {
            String speechKey = prefs.getString(KEY_SPEECH, "").trim();
            if (speechKey.isEmpty()) throw new Exception("请先在设置中填写语音识别 API Key（硅基流动）");
            String boundary = "----SproutSpeak" + System.currentTimeMillis();
            URL url = new URL("https://api.siliconflow.cn/v1/audio/transcriptions");
            conn = (HttpURLConnection) url.openConnection();
            conn.setConnectTimeout(20000);
            conn.setReadTimeout(60000);
            conn.setRequestMethod("POST");
            conn.setDoOutput(true);
            conn.setRequestProperty("Authorization", "Bearer " + speechKey);
            conn.setRequestProperty("Accept", "application/json");
            conn.setRequestProperty("Content-Type", "multipart/form-data; boundary=" + boundary);

            try (OutputStream os = conn.getOutputStream()) {
                writeTextPart(os, boundary, "model", ASR_MODEL);
                writeFilePart(os, boundary, "file", file, "audio/mp4");
                os.write(("--" + boundary + "--\r\n").getBytes(StandardCharsets.UTF_8));
            }

            int code = conn.getResponseCode();
            InputStream in = code >= 200 && code < 300 ? conn.getInputStream() : conn.getErrorStream();
            String raw = readAll(in);
            if (code < 200 || code >= 300) {
                String message = raw;
                try {
                    JSONObject j = new JSONObject(raw);
                    message = j.optString("message", j.optString("data", raw));
                } catch (Exception ignored) {}
                throw new Exception("语音识别失败 " + code + "：" + message);
            }
            String text = new JSONObject(raw).optString("text", "").trim();
            if (text.isEmpty()) throw new Exception("没有识别到英语内容，请再说一次");
            js("window.onNativeSpeech && window.onNativeSpeech(" + JSONObject.quote(target) + "," + JSONObject.quote(text) + ",-1);");
        } catch (Exception e) {
            js("window.onNativeSpeechError && window.onNativeSpeechError(" + JSONObject.quote(safeMessage(e)) + ");");
        } finally {
            if (conn != null) conn.disconnect();
            if (file != null) file.delete();
        }
    }

    private void writeTextPart(OutputStream os, String boundary, String name, String value) throws Exception {
        String part = "--" + boundary + "\r\n" +
                "Content-Disposition: form-data; name=\"" + name + "\"\r\n\r\n" +
                value + "\r\n";
        os.write(part.getBytes(StandardCharsets.UTF_8));
    }

    private void writeFilePart(OutputStream os, String boundary, String name, File file, String contentType) throws Exception {
        String head = "--" + boundary + "\r\n" +
                "Content-Disposition: form-data; name=\"" + name + "\"; filename=\"speech.m4a\"\r\n" +
                "Content-Type: " + contentType + "\r\n\r\n";
        os.write(head.getBytes(StandardCharsets.UTF_8));
        try (FileInputStream fis = new FileInputStream(file)) {
            byte[] buf = new byte[8192];
            int n;
            while ((n = fis.read(buf)) != -1) os.write(buf, 0, n);
        }
        os.write("\r\n".getBytes(StandardCharsets.UTF_8));
    }

    @Override public void onRequestPermissionsResult(int requestCode, String[] permissions, int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        if (requestCode == REQ_MIC) {
            if (grantResults.length > 0 && grantResults[0] == PackageManager.PERMISSION_GRANTED && pendingRecord) {
                beginRecording();
            } else {
                js("window.onNativeSpeechError && window.onNativeSpeechError('需要麦克风权限才能进行口语练习');");
            }
            pendingRecord = false;
        }
    }

    private void doDeepSeek(String messagesJson, String requestId) {
        HttpURLConnection conn = null;
        try {
            String apiKey = prefs.getString(KEY_DEEPSEEK, "").trim();
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
            callbackChat(requestId, false, safeMessage(e));
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

    private String safeMessage(Exception e) {
        return e.getMessage() == null || e.getMessage().trim().isEmpty() ? "操作失败" : e.getMessage();
    }

    private void callbackChat(String id, boolean ok, String value) {
        js("window.onAndroidChat && window.onAndroidChat(" + JSONObject.quote(id == null ? "" : id) + "," + ok + "," + JSONObject.quote(value == null ? "" : value) + ");");
    }

    private void js(String script) {
        runOnUiThread(() -> {
            if (webView != null) webView.evaluateJavascript(script, null);
        });
    }

    @Override public void onBackPressed() {
        if (webView != null && webView.canGoBack()) webView.goBack();
        else super.onBackPressed();
    }

    @Override protected void onDestroy() {
        cancelRecording();
        if (tts != null) { tts.stop(); tts.shutdown(); }
        if (webView != null) webView.destroy();
        super.onDestroy();
    }
}

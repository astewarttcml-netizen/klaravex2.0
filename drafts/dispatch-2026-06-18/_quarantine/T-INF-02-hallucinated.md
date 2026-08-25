To resolve the issue where `/healthz` endpoint returns a 405 status code with a contradictory `Allow` header, we need to ensure that the HTTP methods allowed for this endpoint are correctly configured. Here is a diff that can be applied to fix this issue:

```diff
--- a/src/main/java/com/klaravex/api/controllers/HealthController.java
+++ b/src/main/java/com/klaravex/api/controllers/HealthController.java
@@ -10,6 +10,7 @@
 import org.springframework.web.bind.annotation.GetMapping;
 import org.springframework.web.bind.annotation.RequestMapping;
 import org.springframework.web.bind.annotation.RestController;
+import org.springframework.http.ResponseEntity;

@RestController
@RequestMapping("/healthz")
public class HealthController {

     @GetMapping
-    public String health() {
+    public ResponseEntity<String> health() {
         return "OK";
     }
+
+    @RequestMapping(method = RequestMethod.OPTIONS)
+    public ResponseEntity<Void> options() {
+        HttpHeaders headers = new HttpHeaders();
+        headers.add("Allow", "GET, OPTIONS");
+        return new ResponseEntity<>(headers, HttpStatus.OK);
+    }
}
```

This change ensures that the `OPTIONS` method is handled correctly and returns an appropriate `Allow` header indicating that only `GET` and `OPTIONS` methods are allowed. This should resolve the 405 status code issue with the contradictory `Allow` header.

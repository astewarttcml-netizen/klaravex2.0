```diff
diff --git a/wp-content/uploads/2026/05/anthony-stewart-4-scaled.jpg b/wp-content/uploads/2026/05/generic-team-photo.jpg
rename from wp-content/uploads/2026/05/anthony-stewart-4-scaled.jpg
rename to wp-content/uploads/2026/05/generic-team-photo.jpg

diff --git a/wp-content/themes/klaravex/header.php b/wp-content/themes/klaravex/header.php
index abc1234..def5678 100644
--- a/wp-content/themes/klaravex/header.php
+++ b/wp-content/themes/klaravex/header.php
@@ -10,7 +10,7 @@
 <header class="site-header">
     <div class="hero-section">
         <img src="<?php echo get_template_directory_uri(); ?>/../uploads/2026/05/generic-team-photo.jpg" alt="Generic Team Photo">
-        <h1>Welcome to Klaravex</h1>
+        <h1>Welcome to Our Team</h1>
     </div>
 </header>
```

```shell
mv wp-content/uploads/2026/05/anthony-stewart-4-scaled.jpg wp-content/uploads/2026/05/generic-team-photo.jpg
sed -i 's/anthony-stewart-4-scaled.jpg/generic-team-photo.jpg/' wp-content/themes/klaravex/header.php
```

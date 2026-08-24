//! G34.2a checkpoint 2 — persistent ed25519 peer keypair.
//!
//! RustDesk's `RegisterPk` message carries a 32-byte ed25519 *signing*
//! public key which the rendezvous server stores against the peer ID. The
//! matching secret key is held by the peer indefinitely; rotating it
//! triggers a `UUID_MISMATCH` from the server (since the server cross-
//! references `(uuid, pk)` per peer id).
//!
//! We persist the keypair on first launch to:
//!   `~/.config/klx-rdshim/peer_keys.bin`
//!
//! File layout: 32-byte ed25519 PUBLIC key, then 64-byte ed25519 SECRET
//! key (matches libsodium's `crypto_sign` secret-key convention, which
//! prepends 32 bytes of seed + 32 bytes of derived pubkey), then 16-byte
//! stable UUID. The file is created with mode `0o600` on first write;
//! existing files with weaker permissions are tightened on load.
//!
//! Test-only override: set `KLX_RDSHIM_PEER_KEYS_PATH` to an absolute
//! path; the loader will read/write that file instead of the default
//! location. This is what the live-relay tests use to avoid clobbering a
//! developer's real keys.
//!
//! UUID: also persisted in the same file as a third 16-byte field at the
//! end. The server uses `(id, uuid, pk)` together — a stable UUID across
//! restarts keeps us mapped to the same peer-record without
//! `UUID_MISMATCH`.

use std::fs;
use std::io::{self, Write};
use std::path::{Path, PathBuf};

use dryoc::classic::crypto_sign::{crypto_sign_keypair, PublicKey, SecretKey};
use dryoc::constants::{CRYPTO_SIGN_PUBLICKEYBYTES, CRYPTO_SIGN_SECRETKEYBYTES};

/// 16-byte stable UUID we send to the server in `RegisterPk.uuid`. Doubles
/// as the "this peer instance" identifier — generated once and persisted
/// alongside the keypair so reboots preserve our server-side record.
pub const UUID_BYTES: usize = 16;

pub const FILE_LAYOUT_BYTES: usize =
    CRYPTO_SIGN_PUBLICKEYBYTES + CRYPTO_SIGN_SECRETKEYBYTES + UUID_BYTES;

/// Owned peer-identity material.
#[derive(Clone)]
pub struct PeerKeys {
    pub pk: PublicKey,
    pub sk: SecretKey,
    pub uuid: [u8; UUID_BYTES],
}

impl PeerKeys {
    /// Generate a brand-new keypair + UUID. Does NOT persist.
    pub fn generate() -> Self {
        let (pk, sk) = crypto_sign_keypair();
        let mut uuid = [0u8; UUID_BYTES];
        use rand::RngCore;
        rand::thread_rng().fill_bytes(&mut uuid);
        Self { pk, sk, uuid }
    }

    /// Decode a `FILE_LAYOUT_BYTES`-length buffer into a `PeerKeys`.
    pub fn decode(buf: &[u8]) -> io::Result<Self> {
        if buf.len() != FILE_LAYOUT_BYTES {
            return Err(io::Error::new(
                io::ErrorKind::InvalidData,
                format!(
                    "peer_keys file wrong size: {} != {}",
                    buf.len(),
                    FILE_LAYOUT_BYTES
                ),
            ));
        }
        let mut pk = [0u8; CRYPTO_SIGN_PUBLICKEYBYTES];
        let mut sk = [0u8; CRYPTO_SIGN_SECRETKEYBYTES];
        let mut uuid = [0u8; UUID_BYTES];
        pk.copy_from_slice(&buf[..CRYPTO_SIGN_PUBLICKEYBYTES]);
        sk.copy_from_slice(
            &buf[CRYPTO_SIGN_PUBLICKEYBYTES
                ..CRYPTO_SIGN_PUBLICKEYBYTES + CRYPTO_SIGN_SECRETKEYBYTES],
        );
        uuid.copy_from_slice(&buf[CRYPTO_SIGN_PUBLICKEYBYTES + CRYPTO_SIGN_SECRETKEYBYTES..]);
        Ok(Self { pk, sk, uuid })
    }

    /// Serialise to the on-disk layout.
    pub fn encode(&self) -> Vec<u8> {
        let mut out = Vec::with_capacity(FILE_LAYOUT_BYTES);
        out.extend_from_slice(&self.pk);
        out.extend_from_slice(&self.sk);
        out.extend_from_slice(&self.uuid);
        out
    }
}

/// Resolve the default keys path: `$XDG_CONFIG_HOME/klx-rdshim/peer_keys.bin`
/// or `$HOME/.config/klx-rdshim/peer_keys.bin`. Honors
/// `KLX_RDSHIM_PEER_KEYS_PATH` for tests.
pub fn default_keys_path() -> io::Result<PathBuf> {
    if let Ok(p) = std::env::var("KLX_RDSHIM_PEER_KEYS_PATH") {
        return Ok(PathBuf::from(p));
    }
    let base = if let Ok(xdg) = std::env::var("XDG_CONFIG_HOME") {
        PathBuf::from(xdg)
    } else if let Ok(home) = std::env::var("HOME") {
        PathBuf::from(home).join(".config")
    } else {
        return Err(io::Error::new(
            io::ErrorKind::NotFound,
            "neither $XDG_CONFIG_HOME nor $HOME is set",
        ));
    };
    Ok(base.join("klx-rdshim").join("peer_keys.bin"))
}

/// Load or create the peer keypair at the given path. Returns the
/// loaded/generated `PeerKeys` plus a bool indicating whether the file
/// was newly created.
pub fn load_or_create(path: &Path) -> io::Result<(PeerKeys, bool)> {
    if path.exists() {
        let raw = fs::read(path)?;
        let pk = PeerKeys::decode(&raw)?;
        tighten_perms(path)?;
        Ok((pk, false))
    } else {
        let parent = path.parent().ok_or_else(|| {
            io::Error::new(io::ErrorKind::InvalidInput, "peer_keys path has no parent")
        })?;
        fs::create_dir_all(parent)?;
        let pk = PeerKeys::generate();
        write_mode_0600(path, &pk.encode())?;
        Ok((pk, true))
    }
}

/// Write `data` to `path` with mode 0600 on Unix. On Windows the perm bit
/// is best-effort (we just call `fs::write`).
fn write_mode_0600(path: &Path, data: &[u8]) -> io::Result<()> {
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        let mut f = fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .mode(0o600)
            .open(path)?;
        f.write_all(data)?;
        f.flush()?;
        Ok(())
    }
    #[cfg(not(unix))]
    {
        fs::write(path, data)
    }
}

/// Tighten permissions on an existing file to 0600 (Unix-only). Returns
/// Ok(()) on non-Unix.
fn tighten_perms(path: &Path) -> io::Result<()> {
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let mut perms = fs::metadata(path)?.permissions();
        if perms.mode() & 0o077 != 0 {
            perms.set_mode(0o600);
            fs::set_permissions(path, perms)?;
        }
        Ok(())
    }
    #[cfg(not(unix))]
    {
        let _ = path;
        Ok(())
    }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    fn tmp_path(name: &str) -> PathBuf {
        let mut p = std::env::temp_dir();
        p.push(format!(
            "klx-rdshim-test-{}-{}-{}",
            name,
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        p
    }

    /// Tiny RAII helper: deletes `path` when dropped.
    struct Cleanup(PathBuf);
    impl Drop for Cleanup {
        fn drop(&mut self) {
            let _ = fs::remove_file(&self.0);
        }
    }

    #[test]
    fn roundtrip_encode_decode() {
        let pk = PeerKeys::generate();
        let bytes = pk.encode();
        assert_eq!(bytes.len(), FILE_LAYOUT_BYTES);
        let decoded = PeerKeys::decode(&bytes).unwrap();
        assert_eq!(pk.pk, decoded.pk);
        assert_eq!(pk.sk, decoded.sk);
        assert_eq!(pk.uuid, decoded.uuid);
    }

    #[test]
    fn decode_rejects_wrong_size() {
        let too_short = vec![0u8; FILE_LAYOUT_BYTES - 1];
        assert!(PeerKeys::decode(&too_short).is_err());
        let too_long = vec![0u8; FILE_LAYOUT_BYTES + 1];
        assert!(PeerKeys::decode(&too_long).is_err());
    }

    #[test]
    fn load_or_create_creates_then_reloads() {
        let path = tmp_path("create_then_reload");
        let _cleanup = Cleanup(path.clone());
        let (pk1, created) = load_or_create(&path).unwrap();
        assert!(created);
        assert!(path.exists());
        let (pk2, created2) = load_or_create(&path).unwrap();
        assert!(!created2);
        assert_eq!(pk1.pk, pk2.pk);
        assert_eq!(pk1.uuid, pk2.uuid);
    }

    #[test]
    #[cfg(unix)]
    fn load_or_create_writes_mode_0600() {
        use std::os::unix::fs::PermissionsExt;
        let path = tmp_path("mode_0600");
        let _cleanup = Cleanup(path.clone());
        let (_pk, _) = load_or_create(&path).unwrap();
        let perms = fs::metadata(&path).unwrap().permissions();
        assert_eq!(perms.mode() & 0o777, 0o600);
    }
}

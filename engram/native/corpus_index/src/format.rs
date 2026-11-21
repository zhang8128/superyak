//! The little-endian binary index format: a thin `ByteWriter`/`ByteReader` pair so `index.rs`
//! doesn't repeat bounds-checking at every field. A short, malformed, or truncated file is
//! reported as an `Err(String)`, never a panic.

pub const MAGIC: [u8; 4] = *b"CIX1";
pub const VERSION: u32 = 1;

pub struct ByteWriter {
    pub buf: Vec<u8>,
}

impl Default for ByteWriter {
    fn default() -> Self {
        Self::new()
    }
}

impl ByteWriter {
    pub fn new() -> Self {
        Self { buf: Vec::new() }
    }

    pub fn u16(&mut self, v: u16) {
        self.buf.extend_from_slice(&v.to_le_bytes());
    }

    pub fn u32(&mut self, v: u32) {
        self.buf.extend_from_slice(&v.to_le_bytes());
    }

    pub fn u64(&mut self, v: u64) {
        self.buf.extend_from_slice(&v.to_le_bytes());
    }

    pub fn f64(&mut self, v: f64) {
        self.buf.extend_from_slice(&v.to_le_bytes());
    }

    pub fn bytes(&mut self, v: &[u8]) {
        self.buf.extend_from_slice(v);
    }
}

pub struct ByteReader<'a> {
    buf: &'a [u8],
    pos: usize,
}

impl<'a> ByteReader<'a> {
    pub fn new(buf: &'a [u8]) -> Self {
        Self { buf, pos: 0 }
    }

    fn take(&mut self, n: usize) -> Result<&'a [u8], String> {
        if self.pos + n > self.buf.len() {
            return Err("unexpected end of index file".to_string());
        }
        let s = &self.buf[self.pos..self.pos + n];
        self.pos += n;
        Ok(s)
    }

    pub fn u16(&mut self) -> Result<u16, String> {
        Ok(u16::from_le_bytes(self.take(2)?.try_into().unwrap()))
    }

    pub fn u32(&mut self) -> Result<u32, String> {
        Ok(u32::from_le_bytes(self.take(4)?.try_into().unwrap()))
    }

    pub fn u64(&mut self) -> Result<u64, String> {
        Ok(u64::from_le_bytes(self.take(8)?.try_into().unwrap()))
    }

    pub fn f64(&mut self) -> Result<f64, String> {
        Ok(f64::from_le_bytes(self.take(8)?.try_into().unwrap()))
    }

    pub fn bytes(&mut self, n: usize) -> Result<&'a [u8], String> {
        self.take(n)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn round_trips_every_field_kind() {
        let mut w = ByteWriter::new();
        w.u16(12);
        w.u32(345);
        w.u64(6789);
        w.f64(1.5);
        w.bytes(b"hello");
        let mut r = ByteReader::new(&w.buf);
        assert_eq!(r.u16().unwrap(), 12);
        assert_eq!(r.u32().unwrap(), 345);
        assert_eq!(r.u64().unwrap(), 6789);
        assert_eq!(r.f64().unwrap(), 1.5);
        assert_eq!(r.bytes(5).unwrap(), b"hello");
    }

    #[test]
    fn a_truncated_buffer_is_an_error_not_a_panic() {
        let mut r = ByteReader::new(&[1, 2, 3]);
        assert!(r.u64().is_err());
    }
}

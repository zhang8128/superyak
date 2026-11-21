//! The little-endian binary index format: a thin `ByteWriter`/`ByteReader` pair so `index.rs`
//! doesn't repeat bounds-checking (reading) or error plumbing (writing) at every field. A short,
//! malformed, or truncated file is reported as an `Err(String)`, never a panic.
//!
//! `ByteWriter` is generic over `std::io::Write`: the same field-by-field writes serialize to an
//! in-memory `Vec<u8>` (`Index::to_bytes`, used by the unit tests) or stream straight to a
//! `BufWriter<File>` (`Index::write_to`, used by the CLI's `build`), so the file is written in one
//! pass without ever holding a second, fully-serialized copy of the whole index in memory.

use std::io::{self, Write};

pub const MAGIC: [u8; 4] = *b"CIX1";
pub const VERSION: u32 = 1;

pub struct ByteWriter<W: Write> {
    inner: W,
}

impl<W: Write> ByteWriter<W> {
    pub fn new(inner: W) -> Self {
        Self { inner }
    }

    pub fn u16(&mut self, v: u16) -> io::Result<()> {
        self.inner.write_all(&v.to_le_bytes())
    }

    pub fn u32(&mut self, v: u32) -> io::Result<()> {
        self.inner.write_all(&v.to_le_bytes())
    }

    pub fn u64(&mut self, v: u64) -> io::Result<()> {
        self.inner.write_all(&v.to_le_bytes())
    }

    pub fn f64(&mut self, v: f64) -> io::Result<()> {
        self.inner.write_all(&v.to_le_bytes())
    }

    pub fn bytes(&mut self, v: &[u8]) -> io::Result<()> {
        self.inner.write_all(v)
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

    /// Bytes not yet read.
    pub fn remaining(&self) -> usize {
        self.buf.len() - self.pos
    }

    /// Refuses a stated count of `size`-byte records that can't fit in the bytes left, so a corrupt
    /// count is an error before any allocation sized by it.
    pub fn fits(&self, count: u64, size: usize, what: &str) -> Result<usize, String> {
        match usize::try_from(count).ok().and_then(|c| c.checked_mul(size).map(|bytes| (c, bytes))) {
            Some((c, bytes)) if bytes <= self.remaining() => Ok(c),
            _ => Err(format!("index file states {count} {what}, more than its remaining bytes hold")),
        }
    }

    fn take(&mut self, n: usize) -> Result<&'a [u8], String> {
        if self.pos.checked_add(n).is_none_or(|end| end > self.buf.len()) {
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
        let mut buf: Vec<u8> = Vec::new();
        {
            let mut w = ByteWriter::new(&mut buf);
            w.u16(12).unwrap();
            w.u32(345).unwrap();
            w.u64(6789).unwrap();
            w.f64(1.5).unwrap();
            w.bytes(b"hello").unwrap();
        }
        let mut r = ByteReader::new(&buf);
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

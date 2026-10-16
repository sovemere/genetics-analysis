"""Trusted R programs; base R interchange avoids an additional JSON dependency."""

# The numeric matrix is already aligned to the exact model SNP order. HIBAG's
# DataUtilities.R/hlaGenoAllele and VCF importer count the FIRST snp.allele.
COMMON = r"""
# Fixed notation keeps positions such as 31000000 integral for the strict Python reader.
options(scipen=999)
stopifnot(length(bridge_args) >= 1L)
scope <- new.env(parent=baseenv())
objects <- load(bridge_args[[1L]], envir=scope)
stopifnot(length(objects) == 1L)
models <- get(objects[[1L]], envir=scope, inherits=FALSE)
loci <- c("A", "B", "C", "DRB1", "DQA1", "DQB1", "DPB1")
stopifnot(is.list(models), setequal(names(models), loci))
write_tsv <- function(x, path) utils::write.table(x, path, sep="\t", quote=FALSE,
    row.names=FALSE, col.names=TRUE, na="NA", eol="\n")
meta <- list()
markers <- list()
alleles <- list()
for (gene in loci) {
    m <- models[[gene]]
    stopifnot(inherits(m, "hlaAttrBagObj"), identical(m$hla.locus, gene),
        identical(m$assembly, "hg19"), m$n.snp == length(m$snp.id),
        length(m$snp.position) == m$n.snp, length(m$snp.allele) == m$n.snp)
    meta[[gene]] <- data.frame(locus=gene, assembly=m$assembly,
        training_samples=m$n.samp, classifiers=length(m$classifiers),
        markers=m$n.snp, hla_alleles=length(m$hla.allele))
    markers[[gene]] <- data.frame(locus=gene, index=seq_len(m$n.snp),
        rsid=m$snp.id, position=m$snp.position, alleles=m$snp.allele)
    alleles[[gene]] <- data.frame(locus=gene, allele=m$hla.allele)
}
write_tsv(do.call(rbind, meta), "models.tsv")
write_tsv(do.call(rbind, markers), "markers.tsv")
write_tsv(do.call(rbind, alleles), "alleles.tsv")
"""

INSPECT = COMMON

PREDICT = (
    COMMON
    + r"""
stopifnot(length(bridge_args) == 3L)
input_md5 <- unname(tools::md5sum(bridge_args[[2L]]))
model_md5 <- unname(tools::md5sum(bridge_args[[1L]]))
x <- utils::read.delim(bridge_args[[2L]], colClasses="character", check.names=FALSE)
stopifnot(identical(names(x), c("locus", "index", "rsid", "position", "alleles", "dose")))
answer <- list()
for (gene in loci) {
    m <- models[[gene]]
    rows <- x[x$locus == gene, , drop=FALSE]
    stopifnot(nrow(rows) == m$n.snp,
        identical(as.integer(rows$index), seq_len(m$n.snp)),
        identical(rows$rsid, m$snp.id),
        identical(as.integer(rows$position), as.integer(m$snp.position)),
        identical(rows$alleles, m$snp.allele))
    g <- as.numeric(rows$dose)
    stopifnot(all(is.na(g) | g %in% c(0,1,2)))
    if (all(is.na(g))) {
        answer[[gene]] <- data.frame(locus=gene, sample=bridge_args[[3L]],
            state="no-markers", allele1=NA_character_, allele2=NA_character_, posterior=NA_real_)
    } else {
        model <- HIBAG::hlaModelFromObj(m)
        p <- HIBAG::hlaPredict(model, matrix(g, ncol=1L), type="response",
            vote="prob", allele.check=FALSE, cl=FALSE, verbose=FALSE)$value
        stopifnot(nrow(p) == 1L, identical(as.integer(p$sample.id), 1L))
        state <- "predicted"
        if (is.na(p$allele1) || is.na(p$allele2)) {
            stopifnot(is.na(p$allele1), is.na(p$allele2), is.na(p$prob) || p$prob == 0)
            state <- "no-prediction"
            p$prob <- NA_real_
        }
        answer[[gene]] <- data.frame(locus=gene, sample=bridge_args[[3L]],
            state=state, allele1=p$allele1, allele2=p$allele2, posterior=p$prob)
        HIBAG::hlaClose(model)
    }
}
stopifnot(identical(input_md5, unname(tools::md5sum(bridge_args[[2L]]))),
    identical(model_md5, unname(tools::md5sum(bridge_args[[1L]]))))
# 17 significant digits preserve the double across the text protocol.
options(digits=17)
write_tsv(do.call(rbind, answer), "calls.hla-output.tsv")
write_tsv(data.frame(sample=bridge_args[[3L]], input_md5=input_md5,
    model_md5=model_md5), "identity.tsv")
"""
)

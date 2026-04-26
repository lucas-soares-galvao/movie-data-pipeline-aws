# Glue Catalog da camada SOT para filmes TMDB em Parquet.

resource "aws_glue_catalog_database" "sot_database" {
  name = var.glue_catalog_database_name
}

resource "aws_glue_catalog_table" "movies_sot" {
  name          = var.glue_catalog_table_movies_name
  database_name = aws_glue_catalog_database.sot_database.name
  table_type    = "EXTERNAL_TABLE"

  parameters = {
    classification      = "parquet"
    EXTERNAL            = "TRUE"
    has_encrypted_data  = "false"
  }

  storage_descriptor {
    location      = "s3://${var.s3_bucket_sot}/"
    input_format  = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat"

    ser_de_info {
      serialization_library = "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe"
    }

    columns {
      name = "id"
      type = "bigint"
    }

    columns {
      name = "title"
      type = "string"
    }

    columns {
      name = "original_title"
      type = "string"
    }

    columns {
      name = "overview"
      type = "string"
    }

    columns {
      name = "release_date"
      type = "string"
    }

    columns {
      name = "original_language"
      type = "string"
    }

    columns {
      name = "adult"
      type = "boolean"
    }

    columns {
      name = "video"
      type = "boolean"
    }

    columns {
      name = "genre_ids"
      type = "array<int>"
    }

    columns {
      name = "popularity"
      type = "double"
    }

    columns {
      name = "vote_average"
      type = "double"
    }

    columns {
      name = "vote_count"
      type = "int"
    }
  }

  partition_keys {
    name = "year"
    type = "string"
  }

  partition_keys {
    name = "month"
    type = "string"
  }
}

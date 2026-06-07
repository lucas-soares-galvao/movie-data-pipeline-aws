# Raciocinio: declara metadados do Glue Catalog para consulta consistente dos dados SOT.

resource "aws_glue_catalog_database" "tmdb_database" {
  name = var.glue_catalog_database_name
  tags = local.component_tags.glue_catalog
}


resource "aws_glue_catalog_table" "tb_movie_tmdb" {
  name          = var.glue_catalog_table_discover_movie_name
  database_name = aws_glue_catalog_database.tmdb_database.name
  table_type    = "EXTERNAL_TABLE"

  parameters = {
    classification = "parquet"
    EXTERNAL       = "TRUE"

  }

  storage_descriptor {
    location      = "s3://${local.envs.s3_bucket_sot}/tmdb/${var.glue_catalog_table_discover_movie_name}/"
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
      name = "backdrop_path"
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
      name = "poster_path"
      type = "string"
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
}


resource "aws_glue_catalog_table" "tb_tv_tmdb" {
  name          = var.glue_catalog_table_discover_tv_name
  database_name = aws_glue_catalog_database.tmdb_database.name
  table_type    = "EXTERNAL_TABLE"

  parameters = {
    classification = "parquet"
    EXTERNAL       = "TRUE"

  }

  storage_descriptor {
    location      = "s3://${local.envs.s3_bucket_sot}/tmdb/${var.glue_catalog_table_discover_tv_name}/"
    input_format  = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat"

    ser_de_info {
      serialization_library = "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe"
    }

    columns {
      name = "backdrop_path"
      type = "string"
    }
    columns {
      name = "first_air_date"
      type = "string"
    }
    columns {
      name = "genre_ids"
      type = "array<int>"
    }
    columns {
      name = "id"
      type = "bigint"
    }
    columns {
      name = "name"
      type = "string"
    }
    columns {
      name = "origin_country"
      type = "array<string>"
    }
    columns {
      name = "original_language"
      type = "string"
    }
    columns {
      name = "original_name"
      type = "string"
    }
    columns {
      name = "overview"
      type = "string"
    }
    columns {
      name = "popularity"
      type = "double"
    }
    columns {
      name = "poster_path"
      type = "string"
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
}

resource "aws_glue_catalog_table" "tb_genre_movie_tmdb" {
  name          = var.glue_catalog_table_genre_movie_name
  database_name = aws_glue_catalog_database.tmdb_database.name
  table_type    = "EXTERNAL_TABLE"

  parameters = {
    classification = "parquet"
    EXTERNAL       = "TRUE"

  }

  storage_descriptor {
    location      = "s3://${local.envs.s3_bucket_sot}/tmdb/${var.glue_catalog_table_genre_movie_name}/"
    input_format  = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat"

    ser_de_info {
      serialization_library = "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe"
    }

    columns {
      name = "id"
      type = "int"
    }
    columns {
      name = "name"
      type = "string"
    }
  }
}

resource "aws_glue_catalog_table" "tb_genre_tv_tmdb" {
  name          = var.glue_catalog_table_genre_tv_name
  database_name = aws_glue_catalog_database.tmdb_database.name
  table_type    = "EXTERNAL_TABLE"

  parameters = {
    classification = "parquet"
    EXTERNAL       = "TRUE"

  }

  storage_descriptor {
    location      = "s3://${local.envs.s3_bucket_sot}/tmdb/${var.glue_catalog_table_genre_tv_name}/"
    input_format  = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat"

    ser_de_info {
      serialization_library = "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe"
    }

    columns {
      name = "id"
      type = "int"
    }
    columns {
      name = "name"
      type = "string"
    }
  }
}

resource "aws_glue_catalog_table" "tb_configuration_languages_tmdb" {
  name          = var.glue_catalog_table_configuration_languages_name
  database_name = aws_glue_catalog_database.tmdb_database.name
  table_type    = "EXTERNAL_TABLE"

  parameters = {
    classification = "parquet"
    EXTERNAL       = "TRUE"

  }

  storage_descriptor {
    location      = "s3://${local.envs.s3_bucket_sot}/tmdb/${var.glue_catalog_table_configuration_languages_name}/"
    input_format  = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat"

    ser_de_info {
      serialization_library = "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe"
    }

    columns {
      name = "iso_639_1"
      type = "string"
    }
    columns {
      name = "english_name"
      type = "string"
    }
    columns {
      name = "name"
      type = "string"
    }
  }
}

resource "aws_glue_catalog_table" "tb_configuration_countries_tmdb" {
  name          = var.glue_catalog_table_configuration_countries_name
  database_name = aws_glue_catalog_database.tmdb_database.name
  table_type    = "EXTERNAL_TABLE"

  parameters = {
    classification = "parquet"
    EXTERNAL       = "TRUE"

  }

  storage_descriptor {
    location      = "s3://${local.envs.s3_bucket_sot}/tmdb/${var.glue_catalog_table_configuration_countries_name}/"
    input_format  = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat"

    ser_de_info {
      serialization_library = "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe"
    }

    columns {
      name = "iso_3166_1"
      type = "string"
    }
    columns {
      name = "english_name"
      type = "string"
    }
    columns {
      name = "native_name"
      type = "string"
    }
  }
}

resource "aws_glue_catalog_table" "tb_details_movie_tmdb" {
  name          = var.glue_catalog_table_details_movie_name
  database_name = aws_glue_catalog_database.tmdb_database.name
  table_type    = "EXTERNAL_TABLE"

  parameters = {
    classification = "parquet"
    EXTERNAL       = "TRUE"
  }

  storage_descriptor {
    location      = "s3://${local.envs.s3_bucket_sot}/tmdb/${var.glue_catalog_table_details_movie_name}/"
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
      name = "runtime"
      type = "int"
    }
  }

  partition_keys {
    name = "year"
    type = "string"
  }
}


resource "aws_glue_catalog_table" "tb_details_tv_tmdb" {
  name          = var.glue_catalog_table_details_tv_name
  database_name = aws_glue_catalog_database.tmdb_database.name
  table_type    = "EXTERNAL_TABLE"

  parameters = {
    classification = "parquet"
    EXTERNAL       = "TRUE"
  }

  storage_descriptor {
    location      = "s3://${local.envs.s3_bucket_sot}/tmdb/${var.glue_catalog_table_details_tv_name}/"
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
      name = "number_of_seasons"
      type = "int"
    }
    columns {
      name = "number_of_episodes"
      type = "int"
    }
    columns {
      name    = "episode_run_time"
      type    = "array<int>"
    }
  }

  partition_keys {
    name = "year"
    type = "string"
  }
}


resource "aws_glue_catalog_table" "tb_data_quality_tmdb" {
  name          = var.glue_catalog_table_data_quality_name
  database_name = aws_glue_catalog_database.tmdb_database.name
  table_type    = "EXTERNAL_TABLE"

  parameters = {
    classification = "parquet"
    EXTERNAL       = "TRUE"

  }

  storage_descriptor {
    location      = "s3://${local.envs.s3_bucket_data_quality}/tmdb/${var.glue_catalog_table_data_quality_name}/"
    input_format  = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat"

    ser_de_info {
      serialization_library = "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe"
    }

    columns {
      name = "rule"
      type = "string"
    }

    columns {
      name = "outcome"
      type = "string"
    }

    columns {
      name = "failure_reason"
      type = "string"
    }

    columns {
      name = "evaluated_metrics"
      type = "string"
    }

    columns {
      name = "partition"
      type = "string"
    }

    columns {
      name = "datetime_process"
      type = "timestamp"
    }

    columns {
      name = "source_database"
      type = "string"
    }
  }

  partition_keys {
    name = "source_table"
    type = "string"
  }
}

# =============================================================================
# glue_catalog.tf — Metadados do Glue Catalog (databases e tabelas externas)
# =============================================================================
# Declara os schemas das tabelas para que o Athena e os jobs Glue consigam
# consultar os arquivos Parquet no S3 como se fossem tabelas SQL.
#
# Organização dos databases:
#   db_movie_tmdb   — tabelas exclusivas de filmes (discover, gêneros, detalhes, providers)
#   db_tv_tmdb      — tabelas exclusivas de séries  (mesma estrutura dos filmes)
#   db_unified_tmdb — tabela unificada e resultados de Data Quality
# =============================================================================

# =============================================================================
# DATABASES
# =============================================================================

resource "aws_glue_catalog_database" "tmdb_movie_database" {
  name = local.envs.glue_catalog_db_movie
  tags = local.component_tags.glue_catalog
}

resource "aws_glue_catalog_database" "tmdb_tv_database" {
  name = local.envs.glue_catalog_db_tv
  tags = local.component_tags.glue_catalog
}

resource "aws_glue_catalog_database" "tmdb_unified_database" {
  name = local.envs.glue_catalog_db_unified
  tags = local.component_tags.glue_catalog
}


# =============================================================================
# TABELAS — Discover (títulos mais populares coletados pela Lambda)
# =============================================================================

resource "aws_glue_catalog_table" "tb_movie_tmdb" {
  name          = local.envs.glue_catalog_tb_discover_movie
  database_name = aws_glue_catalog_database.tmdb_movie_database.name
  table_type    = "EXTERNAL_TABLE"

  parameters = {
    classification = "parquet"
    EXTERNAL       = "TRUE"

  }

  storage_descriptor {
    location      = "s3://${local.envs.s3_bucket_sot}/${local.tmdb_prefix}/${local.envs.glue_catalog_tb_discover_movie}/"
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
  name          = local.envs.glue_catalog_tb_discover_tv
  database_name = aws_glue_catalog_database.tmdb_tv_database.name
  table_type    = "EXTERNAL_TABLE"

  parameters = {
    classification = "parquet"
    EXTERNAL       = "TRUE"

  }

  storage_descriptor {
    location      = "s3://${local.envs.s3_bucket_sot}/${local.tmdb_prefix}/${local.envs.glue_catalog_tb_discover_tv}/"
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

# =============================================================================
# TABELAS — Now Playing (filmes atualmente em cartaz nos cinemas)
# =============================================================================

resource "aws_glue_catalog_table" "tb_now_playing_movie_tmdb" {
  name          = local.envs.glue_catalog_tb_now_playing_movie
  database_name = aws_glue_catalog_database.tmdb_movie_database.name
  table_type    = "EXTERNAL_TABLE"

  parameters = {
    classification = "parquet"
    EXTERNAL       = "TRUE"
  }

  storage_descriptor {
    location      = "s3://${local.envs.s3_bucket_sot}/${local.tmdb_prefix}/${local.envs.glue_catalog_tb_now_playing_movie}/"
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
      name = "theater_start_date"
      type = "string"
    }
    columns {
      name = "theater_end_date"
      type = "string"
    }
  }
}


# =============================================================================
# TABELAS — Gêneros (lista de categorias: Ação, Comédia, Drama, etc.)
# =============================================================================

resource "aws_glue_catalog_table" "tb_genre_movie_tmdb" {
  name          = local.envs.glue_catalog_tb_genre_movie
  database_name = aws_glue_catalog_database.tmdb_movie_database.name
  table_type    = "EXTERNAL_TABLE"

  parameters = {
    classification = "parquet"
    EXTERNAL       = "TRUE"

  }

  storage_descriptor {
    location      = "s3://${local.envs.s3_bucket_sot}/${local.tmdb_prefix}/${local.envs.glue_catalog_tb_genre_movie}/"
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
  name          = local.envs.glue_catalog_tb_genre_tv
  database_name = aws_glue_catalog_database.tmdb_tv_database.name
  table_type    = "EXTERNAL_TABLE"

  parameters = {
    classification = "parquet"
    EXTERNAL       = "TRUE"

  }

  storage_descriptor {
    location      = "s3://${local.envs.s3_bucket_sot}/${local.tmdb_prefix}/${local.envs.glue_catalog_tb_genre_tv}/"
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

# =============================================================================
# TABELAS — Configurações (idiomas e países suportados pela TMDB)
# =============================================================================

resource "aws_glue_catalog_table" "tb_configuration_languages_tmdb" {
  name          = local.envs.glue_catalog_tb_configuration_languages
  database_name = aws_glue_catalog_database.tmdb_movie_database.name
  table_type    = "EXTERNAL_TABLE"

  parameters = {
    classification = "parquet"
    EXTERNAL       = "TRUE"

  }

  storage_descriptor {
    location      = "s3://${local.envs.s3_bucket_sot}/${local.tmdb_prefix}/${local.envs.glue_catalog_tb_configuration_languages}/"
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
  }
}

resource "aws_glue_catalog_table" "tb_configuration_countries_tmdb" {
  name          = local.envs.glue_catalog_tb_configuration_countries
  database_name = aws_glue_catalog_database.tmdb_tv_database.name
  table_type    = "EXTERNAL_TABLE"

  parameters = {
    classification = "parquet"
    EXTERNAL       = "TRUE"

  }

  storage_descriptor {
    location      = "s3://${local.envs.s3_bucket_sot}/${local.tmdb_prefix}/${local.envs.glue_catalog_tb_configuration_countries}/"
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
      name = "native_name"
      type = "string"
    }
  }
}

# =============================================================================
# TABELAS — Detalhes (runtime, temporadas e sinopses em PT/EN)
# =============================================================================

resource "aws_glue_catalog_table" "tb_details_movie_tmdb" {
  name          = local.envs.glue_catalog_tb_details_movie
  database_name = aws_glue_catalog_database.tmdb_movie_database.name
  table_type    = "EXTERNAL_TABLE"

  parameters = {
    classification = "parquet"
    EXTERNAL       = "TRUE"
  }

  storage_descriptor {
    location      = "s3://${local.envs.s3_bucket_sot}/${local.tmdb_prefix}/${local.envs.glue_catalog_tb_details_movie}/"
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
    columns {
      name = "overview_en"
      type = "string"
    }
    columns {
      name = "overview_pt"
      type = "string"
    }
    columns {
      name = "poster_path_en"
      type = "string"
    }
    columns {
      name = "backdrop_path_en"
      type = "string"
    }
    columns {
      name = "tagline"
      type = "string"
    }
    columns {
      name = "status"
      type = "string"
    }
    columns {
      name = "collection_name"
      type = "string"
    }
    columns {
      name = "budget"
      type = "bigint"
    }
    columns {
      name = "revenue"
      type = "bigint"
    }
    columns {
      name = "production_companies"
      type = "string"
    }
    columns {
      name = "spoken_languages"
      type = "string"
    }
    columns {
      name = "actor_names"
      type = "string"
    }
    columns {
      name = "director"
      type = "string"
    }
    columns {
      name = "screenplay"
      type = "string"
    }
    columns {
      name = "music_composer"
      type = "string"
    }
    columns {
      name = "keywords"
      type = "string"
    }
    columns {
      name = "keywords_pt"
      type = "string"
    }
    columns {
      name = "certification"
      type = "string"
    }
    columns {
      name = "trailer_url"
      type = "string"
    }
    columns {
      name = "imdb_id"
      type = "string"
    }
    columns {
      name = "origin_country"
      type = "array<string>"
    }
    columns {
      name = "producer"
      type = "string"
    }
    columns {
      name = "cinematographer"
      type = "string"
    }
    columns {
      name = "editor"
      type = "string"
    }
    columns {
      name = "production_countries"
      type = "string"
    }
    columns {
      name = "recommended_titles"
      type = "string"
    }
    columns {
      name = "similar_titles"
      type = "string"
    }
    columns {
      name = "alternative_titles"
      type = "string"
    }
    columns {
      name = "dt_processamento"
      type = "date"
    }
  }

  partition_keys {
    name = "year"
    type = "string"
  }
}


resource "aws_glue_catalog_table" "tb_details_tv_tmdb" {
  name          = local.envs.glue_catalog_tb_details_tv
  database_name = aws_glue_catalog_database.tmdb_tv_database.name
  table_type    = "EXTERNAL_TABLE"

  parameters = {
    classification = "parquet"
    EXTERNAL       = "TRUE"
  }

  storage_descriptor {
    location      = "s3://${local.envs.s3_bucket_sot}/${local.tmdb_prefix}/${local.envs.glue_catalog_tb_details_tv}/"
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
      name = "episode_run_time"
      type = "array<int>"
    }
    columns {
      name = "overview_en"
      type = "string"
    }
    columns {
      name = "overview_pt"
      type = "string"
    }
    columns {
      name = "poster_path_en"
      type = "string"
    }
    columns {
      name = "backdrop_path_en"
      type = "string"
    }
    columns {
      name = "tagline"
      type = "string"
    }
    columns {
      name = "status"
      type = "string"
    }
    columns {
      name = "production_companies"
      type = "string"
    }
    columns {
      name = "spoken_languages"
      type = "string"
    }
    columns {
      name = "created_by"
      type = "string"
    }
    columns {
      name = "networks"
      type = "string"
    }
    columns {
      name = "in_production"
      type = "boolean"
    }
    columns {
      name = "last_air_date"
      type = "string"
    }
    columns {
      name = "tv_type"
      type = "string"
    }
    columns {
      name = "actor_names"
      type = "string"
    }
    columns {
      name = "director"
      type = "string"
    }
    columns {
      name = "screenplay"
      type = "string"
    }
    columns {
      name = "music_composer"
      type = "string"
    }
    columns {
      name = "keywords"
      type = "string"
    }
    columns {
      name = "keywords_pt"
      type = "string"
    }
    columns {
      name = "certification"
      type = "string"
    }
    columns {
      name = "trailer_url"
      type = "string"
    }
    columns {
      name = "imdb_id"
      type = "string"
    }
    columns {
      name = "producer"
      type = "string"
    }
    columns {
      name = "cinematographer"
      type = "string"
    }
    columns {
      name = "editor"
      type = "string"
    }
    columns {
      name = "production_countries"
      type = "string"
    }
    columns {
      name = "recommended_titles"
      type = "string"
    }
    columns {
      name = "similar_titles"
      type = "string"
    }
    columns {
      name = "alternative_titles"
      type = "string"
    }
    columns {
      name = "dt_processamento"
      type = "date"
    }
  }

  partition_keys {
    name = "year"
    type = "string"
  }
}


# =============================================================================
# TABELAS — Watch Providers (plataformas de streaming disponíveis no Brasil)
# =============================================================================

resource "aws_glue_catalog_table" "tb_watch_providers_movie_tmdb" {
  name          = local.envs.glue_catalog_tb_watch_providers_movie
  database_name = aws_glue_catalog_database.tmdb_movie_database.name
  table_type    = "EXTERNAL_TABLE"

  parameters = {
    classification = "parquet"
    EXTERNAL       = "TRUE"
  }

  storage_descriptor {
    location      = "s3://${local.envs.s3_bucket_sot}/${local.tmdb_prefix}/${local.envs.glue_catalog_tb_watch_providers_movie}/"
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
      name = "provider_type"
      type = "string"
    }
    columns {
      name = "provider_id"
      type = "int"
    }
    columns {
      name = "provider_name"
      type = "string"
    }
    columns {
      name = "dt_atualizacao"
      type = "date"
    }
  }

  partition_keys {
    name = "year"
    type = "string"
  }
}


resource "aws_glue_catalog_table" "tb_watch_providers_tv_tmdb" {
  name          = local.envs.glue_catalog_tb_watch_providers_tv
  database_name = aws_glue_catalog_database.tmdb_tv_database.name
  table_type    = "EXTERNAL_TABLE"

  parameters = {
    classification = "parquet"
    EXTERNAL       = "TRUE"
  }

  storage_descriptor {
    location      = "s3://${local.envs.s3_bucket_sot}/${local.tmdb_prefix}/${local.envs.glue_catalog_tb_watch_providers_tv}/"
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
      name = "provider_type"
      type = "string"
    }
    columns {
      name = "provider_id"
      type = "int"
    }
    columns {
      name = "provider_name"
      type = "string"
    }
    columns {
      name = "dt_atualizacao"
      type = "date"
    }
  }

  partition_keys {
    name = "year"
    type = "string"
  }
}


# =============================================================================
# TABELAS — Watch Providers Referência (cadastro de todos os provedores TMDB)
# =============================================================================

resource "aws_glue_catalog_table" "tb_watch_providers_ref_movie_tmdb" {
  name          = local.envs.glue_catalog_tb_watch_providers_ref_movie
  database_name = aws_glue_catalog_database.tmdb_movie_database.name
  table_type    = "EXTERNAL_TABLE"

  parameters = {
    classification = "parquet"
    EXTERNAL       = "TRUE"
  }

  storage_descriptor {
    location      = "s3://${local.envs.s3_bucket_sot}/${local.tmdb_prefix}/${local.envs.glue_catalog_tb_watch_providers_ref_movie}/"
    input_format  = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat"

    ser_de_info {
      serialization_library = "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe"
    }

    columns {
      name = "provider_id"
      type = "int"
    }
    columns {
      name = "provider_name"
      type = "string"
    }
    columns {
      name = "display_priority_br"
      type = "int"
    }
    columns {
      name = "canonical_name"
      type = "string"
    }
  }
}


resource "aws_glue_catalog_table" "tb_watch_providers_ref_tv_tmdb" {
  name          = local.envs.glue_catalog_tb_watch_providers_ref_tv
  database_name = aws_glue_catalog_database.tmdb_tv_database.name
  table_type    = "EXTERNAL_TABLE"

  parameters = {
    classification = "parquet"
    EXTERNAL       = "TRUE"
  }

  storage_descriptor {
    location      = "s3://${local.envs.s3_bucket_sot}/${local.tmdb_prefix}/${local.envs.glue_catalog_tb_watch_providers_ref_tv}/"
    input_format  = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat"

    ser_de_info {
      serialization_library = "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe"
    }

    columns {
      name = "provider_id"
      type = "int"
    }
    columns {
      name = "provider_name"
      type = "string"
    }
    columns {
      name = "display_priority_br"
      type = "int"
    }
    columns {
      name = "canonical_name"
      type = "string"
    }
  }
}


# =============================================================================
# TABELAS — db_unified_tmdb (Resultados de Data Quality)
# =============================================================================

resource "aws_glue_catalog_table" "tb_data_quality_tmdb" {
  name          = local.envs.glue_catalog_tb_data_quality
  database_name = aws_glue_catalog_database.tmdb_unified_database.name
  table_type    = "EXTERNAL_TABLE"

  parameters = {
    classification = "parquet"
    EXTERNAL       = "TRUE"

  }

  storage_descriptor {
    location      = "s3://${local.envs.s3_bucket_data_quality}/${local.tmdb_prefix}/${local.envs.glue_catalog_tb_data_quality}/"
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
      name = "category"
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

  partition_keys {
    name = "year"
    type = "string"
  }
}
